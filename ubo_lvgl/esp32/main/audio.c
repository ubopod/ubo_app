#include "audio.h"

#include <string.h>

#include "board.h"
#include "driver/i2s_std.h"
#include "esp_codec_dev.h"
#include "esp_heap_caps.h"
#include "mbedtls/base64.h"
#ifdef CONFIG_UBO_AFE_ENABLE
#include "esp_afe_config.h"
#include "esp_afe_sr_iface.h"
#include "esp_afe_sr_models.h"
#endif
#ifdef CONFIG_UBO_WAKE_ENABLE
/* esp_wn_models.h (ESP_WN_PREFIX) and model_path.h (esp_srmodel_*) both arrive
 * via esp_afe_config.h above.
 *
 * esp-sr only accepts 0.4..0.9999 for set_wakenet_threshold(); 0 means "keep
 * the model's own threshold". Catch a nonsense Kconfig value at build time
 * rather than silently ignoring it on the device. */
_Static_assert(CONFIG_UBO_WAKE_THRESHOLD_PCT == 0 ||
                   (CONFIG_UBO_WAKE_THRESHOLD_PCT >= 40 &&
                    CONFIG_UBO_WAKE_THRESHOLD_PCT <= 99),
               "UBO_WAKE_THRESHOLD_PCT must be 0 (model default) or 40..99");
#endif
#include "esp_codec_dev_defaults.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/stream_buffer.h"
#include "freertos/task.h"
#include "freertos/idf_additions.h"

static const char *TAG = "ubo_audio";

/* ── Audio pin map, from the selected board's board_pins.h (via board.h) ──
 * The codec chips themselves are constructed by board_audio_codecs_init(); this
 * file only owns the I2S channel pair, the buffering and the play/mic state
 * machine. The speaker power amplifier is likewise the board's business
 * (board_speaker_amp_enable) — it is an IO-expander pin on one board and a
 * plain GPIO on another. */
#define I2S_MCLK_GPIO BOARD_I2S_MCLK_GPIO
#define I2S_BCLK_GPIO BOARD_I2S_BCLK_GPIO
#define I2S_WS_GPIO BOARD_I2S_WS_GPIO
#define I2S_DOUT_GPIO BOARD_I2S_DOUT_GPIO /* I2S -> codec DAC -> speaker */
#define I2S_DIN_GPIO BOARD_I2S_DIN_GPIO   /* codec ADC (mic) -> I2S */

#define MIC_RATE 16000 /* PTT capture: 16 kHz mono 16-bit (matches web UI) */
#define MIC_FRAME_MS 20
#define MIC_BYTES_PER_MS (MIC_RATE / 1000 * 2) /* mono 16-bit */
#define MIC_FRAME_BYTES (MIC_FRAME_MS * MIC_BYTES_PER_MS)

#ifndef CONFIG_UBO_MIC_CHUNK_MS
#define CONFIG_UBO_MIC_CHUNK_MS 200
#endif
/* Capture buffer: round the chunk up to a whole number of 20 ms frames, + 1. */
#define MIC_CHUNK_FRAMES (CONFIG_UBO_MIC_CHUNK_MS / MIC_FRAME_MS + 1)
#define MIC_BUF_BYTES (MIC_CHUNK_FRAMES * MIC_FRAME_BYTES)

/* Playback jitter buffer. Sizing is driven by the WORST-case stream, not the
 * mic rate: ubo-core's TTS arrives at 48 kHz mono 16-bit = 96 KB/s, so the
 * original 16384 held only ~170 ms and underran on any hiccup.
 *
 * On a PSRAM board this lives in PSRAM. It is crossed twice per byte, but in
 * 1KB memcpy blocks (efficient burst access), and internal RAM is far too
 * scarce to spend 48KB here — doing so starved the WiFi driver's RX buffers at
 * init and produced a boot loop ("wifi:malloc buffer fail" -> abort). */
#ifdef CONFIG_SPIRAM
#define PLAY_RING_BYTES 98304 /* ~1.0 s @ 48 kHz, ~3 s @ 16 kHz */
#else
#define PLAY_RING_BYTES 16384 /* ~170 ms @ 48 kHz, ~0.5 s @ 16 kHz */
#endif
#define PLAY_DRAIN_CHUNK 1024

#ifndef CONFIG_UBO_AUDIO_GAIN_PERCENT
#define CONFIG_UBO_AUDIO_GAIN_PERCENT 300 /* tiny onboard speaker; 100 = unity */
#endif

/* Apply digital gain (with int16 hard-clamp) to a mono 16-bit PCM chunk. */
static void apply_gain(uint8_t *buf, size_t n) {
    if (CONFIG_UBO_AUDIO_GAIN_PERCENT == 100) {
        return;
    }
    int16_t *s = (int16_t *)buf;
    size_t count = n / sizeof(int16_t);
    for (size_t i = 0; i < count; i++) {
        int32_t v = (int32_t)s[i] * CONFIG_UBO_AUDIO_GAIN_PERCENT / 100;
        s[i] = (int16_t)(v > 32767 ? 32767 : (v < -32768 ? -32768 : v));
    }
}
/* How long the output may sit empty before we close the codec and drop the PA.
 * This must be comfortably longer than the worst gap BETWEEN chunks of one
 * utterance, or every gap tears the codec down and brings it back — which is
 * audible as chopped, clicking speech rather than a clean pause. Closing is
 * only a power optimization; being late costs nothing but a little idle
 * current. */
#ifdef CONFIG_UBO_WAKE_ENABLE
/* With a wake word, this is no longer only a power optimization: the microphone
 * cannot reopen until the output is closed, so the device stays deaf for this
 * long after every reply. 800ms still clears the worst measured inter-chunk gap
 * of an utterance (222-240ms, see AFE-FAR-FIELD.md) by more than 3x. */
#define PLAY_IDLE_CLOSE_US 800000 /* 0.8 s */
/* Upper bound on a wake-started session before the device ends it itself. Only
 * a backstop against a lost start action — a real turn is ended by ubo-core's
 * silence policy long before this, so it should never fire in normal use. */
#define SESSION_MAX_US 120000000LL /* 120 s */
#else
#define PLAY_IDLE_CLOSE_US 2000000 /* 2 s */
#endif


/* Push-to-talk capture task stack. The Xtensa (S3) windowed ABI uses noticeably
 * more stack per frame than the C6's RISC-V, and this task is spawned late —
 * after WiFi, LVGL and the client tasks have already taken their internal RAM —
 * so it is the first thing to fail when internal DRAM runs short. */
#if CONFIG_IDF_TARGET_ARCH_XTENSA
#define MIC_TASK_STACK 5120
#else
#define MIC_TASK_STACK 4096
#endif

/* True when the front end is compiled in AND came up. AFE creation is
 * non-fatal, so capture must still work when it didn't. */
#ifdef CONFIG_UBO_AFE_ENABLE
#define AFE_ACTIVE (a.afe_data != NULL)
/* Matches esp-skainet. These two stacks live in PSRAM (see afe_setup), so they
 * cost nothing from the internal pool — which is the binding constraint on this
 * board and is fully spoken for by WiFi, the client and the LVGL draw buffers.
 * PSRAM stacks are legal for these tasks because neither runs with the flash
 * cache disabled; they only ever touch the codec, AFE and the client callback. */
#define AFE_TASK_STACK 8192

/* Two microphones plus a zero-filled playback reference.
 *
 * The board has no reference wired, so "MM" looks correct — but Espressif's own
 * far-field demo for this hardware (esp-box factory_demo app_sr.c) reads two
 * channels off the ES7210 and then EXPANDS them to three, zeroing the third,
 * before feeding AFE. Feeding two channels while AFE reported
 * raw_data_channels=3 meant it was reading a channel we never supplied, which
 * is consistent with SE(BSS) emitting noise. */
#define AFE_INPUT_FORMAT "MM"
#define AFE_MIC_CHANNELS 2

/* See the task-creation comment in afe_setup() for why this moves with the
 * wake word. */
#ifdef CONFIG_UBO_WAKE_ENABLE
#define AFE_FETCH_CORE 1
#else
#define AFE_FETCH_CORE 0
#endif
#else
#define AFE_ACTIVE 0
#endif

/* What the codec is currently being used for. The microphone and the speaker
 * cannot both be open: they share one I2S port (and therefore one bit clock),
 * and esp_codec_dev's check_fs_compatible() refuses to open the paired device
 * at a different sample rate — 16kHz capture against 48kHz TTS is rejected
 * outright. So this is a hardware arbitration state, not a policy choice.
 *
 * IDLE_WAKE  mic open, fed to AFE, output DISCARDED except wake detection
 * STREAMING  same capture, output pushed to the ring and on to the core
 * PLAYING    mic closed, speaker open; capture tasks parked
 *
 * Without CONFIG_UBO_WAKE_ENABLE only STREAMING and PLAYING occur, and the
 * behaviour is exactly what `mic_active` used to express. */
typedef enum {
    UBO_AUDIO_PLAYING = 0, /* zero value: the state at boot, codec idle */
    UBO_AUDIO_IDLE_WAKE,
    UBO_AUDIO_STREAMING,
} ubo_audio_mode_t;

/* Kept as a macro so every existing `mic_active` test reads the same and means
 * the same: "a talk session is open, playback must not touch the codec". */
#define MIC_STREAMING() (a.mode == UBO_AUDIO_STREAMING)

/* The two ways the capture tasks stop reading, kept apart because they have
 * different consequences: a pause hands the codec to the speaker and the tasks
 * will be released again, a stop ends the session. */
#ifdef CONFIG_UBO_WAKE_ENABLE
#define CAPTURE_PAUSED() (a.capture_pause)
#else
#define CAPTURE_PAUSED() 0
#endif
#define CAPTURE_RUNNING() (!a.mic_stop && !CAPTURE_PAUSED())

/* Defined for every board, AFE or not: the play task exists on all of them.
 * The C6 is single-core, where core 1 does not exist and tskNO_AFFINITY is the
 * only sensible answer. */
#if CONFIG_FREERTOS_NUMBER_OF_CORES > 1
#define PLAY_TASK_CORE 0
#else
#define PLAY_TASK_CORE tskNO_AFFINITY
#endif

static struct {
    /* Codec device handles, supplied by board_audio_codecs_init(). On boards
     * where one chip does both directions these alias the same IN_OUT handle;
     * on the ESP32-S3-BOX-3 they are distinct (ES8311 DAC + ES7210 mic ADC)
     * sharing one I2S data interface. */
    esp_codec_dev_handle_t out_dev;
    esp_codec_dev_handle_t in_dev;
    float mic_gain_db;
#ifdef CONFIG_UBO_AFE_ENABLE
    const esp_afe_sr_iface_t *afe;
    esp_afe_sr_data_t *afe_data;
    int16_t *afe_feed_buf;
    size_t afe_feed_bytes;
    int16_t *afe_mic_buf;   /* codec side: AFE_MIC_CHANNELS interleaved */
    size_t afe_mic_bytes;
    SemaphoreHandle_t afe_go_feed;  /* mic_start -> feed task */
    SemaphoreHandle_t afe_go_fetch; /* mic_start -> fetch task */
    SemaphoreHandle_t afe_feed_idle; /* feed task -> fetch task, before close */
    /* Elastic buffer between capture and the network. Capture is real-time and
     * unrepeatable; dispatch is a blocking POST with a long tail. Coupling them
     * meant a slow POST stalled feed(), the I2S DMA overran, and 3-10% of every
     * utterance was lost at the microphone — audible as words spliced out. */
    StreamBufferHandle_t mic_ring;
    size_t mic_dropped;
    /* True only when a WakeNet model actually resolved and survived
     * afe_config_check(). Not the same as CONFIG_UBO_WAKE_ENABLE: a missing or
     * unreadable `model` partition leaves the wake word off and the device on
     * the push-to-talk-only path, which must keep working. */
    bool wake_active;
    /* The literal phrase the loaded model listens for ("Jarvis"), read out of
     * the model's own _MODEL_INFO_ rather than hardcoded — it has to match what
     * we send ubo-core as WakePhraseTriggerSource.phrase, and the model is a
     * build-time choice.
     *
     * esp_srmodel_get_wake_words() mallocs a fresh string and nothing frees it,
     * so this is a deliberate one-off allocation at boot, NOT a borrowed
     * pointer into the model list. Do not call it per detection. */
    const char *wake_phrase;
    ubo_audio_wake_cb wake_cb;
    void *wake_user;
    /* Where a wake-started session streams to. Held separately from mic_cb so
     * the callback is already in place when the capture task flips to
     * STREAMING, rather than being installed a round trip later by the
     * dispatcher. */
    ubo_audio_mic_cb wake_mic_cb;
    void *wake_mic_user;
    /* Hardware mute. Blocks re-arming; the transition into it closes the
     * microphone through the same pause path the speaker uses. */
    volatile bool wake_muted;
    /* Nothing listens until ubo_audio_wake_bind() says so. Deliberately NOT
     * armed from ubo_audio_init(): that runs before the input task exists (so
     * the mute switch has not been read yet) and, on a board with no stored
     * credentials, before a captive portal that never starts one at all. The
     * device would then sit in its setup portal with the microphone open and
     * the mute switch inert. */
    volatile bool wake_armed;
    /* Set once if the feed task never leaves esp_codec_dev_read(). Stops the
     * re-arm gate from cycling back into a listening state that cannot hear
     * anything, which would otherwise look like a wake word that just stopped
     * working. One-way: it means the codec driver is stuck, so only a reboot
     * clears it. */
    volatile bool capture_wedged;
    /* Consecutive failed hand-offs. Reset by any clean teardown, so only a
     * genuinely stuck driver accumulates enough to latch `capture_wedged`. */
    unsigned wedge_count;
    /* When the current streaming session began, for the local watchdog. Only a
     * message from the core normally ends a wake session, so a start action
     * that never lands would otherwise leave the microphone open and all
     * playback refused until reboot. */
    int64_t session_started_us;
#endif
    i2s_chan_handle_t tx;
    i2s_chan_handle_t rx;
    SemaphoreHandle_t lock; /* serializes dev open/close + mode transitions */
    StreamBufferHandle_t play_ring;

    bool out_open;
    /* Capture-device counterpart of out_open. esp_codec_dev refcounts opens, so
     * an unbalanced pair does not fail loudly — it leaves the microphone half
     * open and the speaker unable to claim the codec, long after the mistake. */
    bool in_open;
    int out_rate, out_ch, out_width;
    /* Format/volume of the sequence currently being fed (set by ubo_audio_play). */
    int want_rate, want_ch, want_width;
    float want_vol;
    int64_t last_feed_us;

#ifdef CONFIG_UBO_MIC_SESSION_RECORDER
    /* Whole-session capture recorder (debug, see UBO_MIC_SESSION_RECORDER).
     * Records exactly the bytes handed upstream, in PSRAM, and dumps only
     * AFTER the session ends — dumping inline would itself stall capture and
     * make the recording unrepresentative of what the core actually receives. */
    uint8_t *rec_buf;
    size_t rec_len;
    size_t rec_cap;
#endif
    volatile ubo_audio_mode_t mode;
    volatile bool mic_stop;
#ifdef CONFIG_UBO_WAKE_ENABLE
    /* Set by play_task to ask the capture tasks to release the codec, cleared
     * once it hands the codec back. Distinct from `mic_stop`, which ends a
     * *session*: a pause keeps the session's identity (and the wake word armed)
     * and only yields the hardware. */
    volatile bool capture_pause;
    SemaphoreHandle_t afe_idle; /* capture tasks -> play_task, codec released */
    /* Earliest time the wake word may re-arm after the speaker falls silent.
     * Covers speaker decay and room reverb; without it the device wakes itself
     * on the tail of its own reply. */
    int64_t wake_resume_at_us;
#endif
    volatile bool flush; /* discard buffered playback (AudioStopPlaybackEvent) */
    /* Playback chunks discarded without ever reaching the speaker. Both drops
     * are silent by design and sound identical from the outside (choppy
     * speech), so they are counted separately to tell them apart. */
    unsigned drops_ring_full; /* no room within the deadline */
    unsigned drops_mic_active; /* refused because a talk session is open */
    /* Mid-stream gaps: the ring ran dry while the codec was open, i.e. nobody
     * refused audio -- it just never arrived in time. This is what CPU
     * starvation of the feeding task sounds like, and no drop counter sees it. */
    unsigned underruns;
    ubo_audio_mic_cb mic_cb;
    void *mic_user;
} a;

/* ── I2S full-duplex std channel (left disabled; esp_codec_dev enables on open) ── */
static esp_err_t i2s_setup(void) {
    i2s_chan_config_t cc = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    cc.auto_clear = true; /* zero the TX DMA on underrun to avoid noise */
    /* Leave the DMA at IDF defaults. Enlarging it to 8x512 needed ~32KB of
     * internal DMA memory for TX+RX, which is not available once a session
     * starts: the allocation failed and the codec open path then panicked
     * (LoadProhibited). Capture headroom now comes from the PSRAM ring and
     * from keeping the feed task on its own core, neither of which competes
     * for internal RAM. */
    esp_err_t err = i2s_new_channel(&cc, &a.tx, &a.rx);
    if (err != ESP_OK) {
        return err;
    }
    const i2s_std_config_t std = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(MIC_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT,
                                                        I2S_SLOT_MODE_MONO),
        .gpio_cfg =
            {
                .mclk = I2S_MCLK_GPIO,
                .bclk = I2S_BCLK_GPIO,
                .ws = I2S_WS_GPIO,
                .dout = I2S_DOUT_GPIO,
                .din = I2S_DIN_GPIO,
            },
    };
    if ((err = i2s_channel_init_std_mode(a.tx, &std)) != ESP_OK ||
        (err = i2s_channel_init_std_mode(a.rx, &std)) != ESP_OK) {
        return err;
    }
    return ESP_OK;
}

/* ── capture open (must hold a.lock) ──
 * AFE needs both microphone channels; the plain path asks for one and the i2s
 * data interface maps that to slot 0. Callers must have closed the output
 * first: one I2S port, one clock, and esp_codec_dev refuses a paired open at a
 * different rate. */
static int open_in(void) {
    if (a.in_open) {
        /* Tracked explicitly rather than inferred from `mode`, so the two can
         * never disagree. esp_codec_dev refcounts opens, so a double-open would
         * need a matching double-close to actually release the device — an
         * imbalance that only shows up much later, as a microphone that will
         * not let the speaker have the codec. */
        return 0;
    }
    const uint8_t mic_channels = AFE_ACTIVE ? 2 : 1;
    esp_codec_dev_sample_info_t fs = {
        .bits_per_sample = 16,
        .channel = mic_channels,
        .sample_rate = MIC_RATE,
    };
    if (esp_codec_dev_open(a.in_dev, &fs) != 0) {
        ESP_LOGE(TAG, "codec open(mic) failed");
        return -1;
    }
    a.in_open = true;
    /* Re-apply after open. NOTE: in 2-channel (AFE) mode the captured level
     * comes out ~36dB lower than the mono path at the same setting — raw peaks
     * of ~500 vs clipping at 32767 — which starves AFE's AGC and makes it
     * amplify the noise floor instead of speech. */
    esp_codec_dev_set_in_gain(a.in_dev, a.mic_gain_db);
    return 0;
}

/* ── output open/close (must hold a.lock) ── */
static int open_out(int rate, int ch, int width, float vol) {
    esp_codec_dev_sample_info_t fs = {
        .bits_per_sample = (uint8_t)(width * 8),
        .channel = (uint8_t)ch,
        .sample_rate = (uint32_t)rate,
    };
    int r = esp_codec_dev_open(a.out_dev, &fs);
    if (r != 0) {
        ESP_LOGE(TAG, "codec open(out) failed: %d", r);
        return r;
    }
    int v = (int)(vol * 100.0f);
    esp_codec_dev_set_out_vol(a.out_dev, v < 0 ? 0 : (v > 100 ? 100 : v));
    ESP_LOGI(TAG, "codec open(out) ok: %d Hz, %d ch, %d-bit, vol=%d", rate, ch,
             width * 8, v < 0 ? 0 : (v > 100 ? 100 : v));
    a.out_open = true;
    a.out_rate = rate;
    a.out_ch = ch;
    a.out_width = width;
    return 0;
}

static void close_out(void) {
    if (a.out_open) {
        esp_codec_dev_close(a.out_dev); /* also drops PA via the codec gpio_if */
        a.out_open = false;
    }
}

/* Mirror of close_out for the capture side (must hold a.lock). */
static void close_in(void) {
    if (a.in_open) {
        esp_codec_dev_close(a.in_dev);
        a.in_open = false;
    }
}

#ifdef CONFIG_UBO_WAKE_ENABLE
/* Arm the wake word: open the microphone and let the AFE tasks run with their
 * output discarded, listening for the wake phrase. Must hold a.lock, and the
 * output must already be closed.
 *
 * play_task is the ONLY caller — it is the task that knows the speaker is
 * finished, and funnelling every entry into IDLE_WAKE through one place is what
 * keeps the arbitration reasonable. Everything else just leaves the codec in
 * PLAYING (i.e. free) and lets play_task pick it up on its next 50ms cycle. */
static void wake_listen_start(void) {
    if (open_in() != 0) {
        /* Back off a second before trying again. play_task cycles every 50ms,
         * so retrying immediately would repeat open_in()'s error log 20 times a
         * second and bury whatever actually went wrong. */
        a.wake_resume_at_us = esp_timer_get_time() + 1000000;
        return;
    }
    /* Drop whatever AFE was holding from before the pause — including the tail
     * of our own playback and, importantly, WakeNet's ~1.5s receptive field,
     * which would otherwise still contain pre-pause audio. */
    a.afe->reset_buffer(a.afe_data);
    a.mic_stop = false;
    a.capture_pause = false;
    a.mode = UBO_AUDIO_IDLE_WAKE;
    /* Start from a known semaphore state. A teardown that timed out can leave
     * `afe_feed_idle` signalled with nobody waiting, and that stale token would
     * satisfy the NEXT teardown's barrier instantly — closing the codec while
     * the feed task is still reading from it, every time, for the rest of the
     * boot. Draining costs nothing and stops one bad teardown from poisoning
     * all the others. */
    xSemaphoreTake(a.afe_feed_idle, 0);
    xSemaphoreTake(a.afe_go_feed, 0);
    xSemaphoreTake(a.afe_go_fetch, 0);
    xSemaphoreTake(a.afe_idle, 0);
    /* Fetch first, so it is waiting on AFE before any data arrives. */
    xSemaphoreGive(a.afe_go_fetch);
    xSemaphoreGive(a.afe_go_feed);
}
#endif

/* ── playback task: drain the ring into the codec, manage rate + idle close ── */
static void play_task(void *arg) {
    (void)arg;
    uint8_t buf[PLAY_DRAIN_CHUNK];
    for (;;) {
        size_t n = xStreamBufferReceive(a.play_ring, buf, sizeof(buf),
                                        pdMS_TO_TICKS(50));
        xSemaphoreTake(a.lock, portMAX_DELAY);
        if (a.flush) {
            /* Reset is safe here: this is the only receiver (and it isn't
             * blocked), and the sender never blocks on the buffer (0-timeout
             * send). The chunk just pulled is pre-stop audio — discard it. */
            a.flush = false;
            xStreamBufferReset(a.play_ring);
            n = 0;
        }
        if (MIC_STREAMING()) {
            /* Don't play during a talk session; discard any stale audio. */
            if (n > 0) {
                xStreamBufferReset(a.play_ring);
            }
            close_out();
            xSemaphoreGive(a.lock);
            continue;
        }
#ifdef CONFIG_UBO_WAKE_ENABLE
        if (n > 0 && a.mode == UBO_AUDIO_IDLE_WAKE) {
            /* The wake word owns the codec and we need it back. Ask the capture
             * tasks to stand down and wait for them to leave
             * esp_codec_dev_read() before anything closes it underneath them.
             *
             * Drain a stale token first: a previous timed-out request may have
             * been satisfied late, and that token must not be mistaken for this
             * request completing. */
            xSemaphoreTake(a.afe_idle, 0);
            a.capture_pause = true;
            /* Released deliberately: the capture teardown path takes a.lock in
             * mic_release(), so holding it here would deadlock against the very
             * task we are waiting for. */
            xSemaphoreGive(a.lock);
            if (xSemaphoreTake(a.afe_idle, pdMS_TO_TICKS(300)) != pdTRUE) {
                /* Capture did not yield in time. Drop this chunk and retry on
                 * the next cycle — but LEAVE `capture_pause` SET.
                 *
                 * Revoking it here was a genuine bug: the capture tasks may
                 * already have observed the request and be unwinding, and
                 * clearing it mid-teardown puts the feed task straight back
                 * into esp_codec_dev_read() while the fetch task walks on to
                 * close that very device. The request is one-way — only the
                 * capture tasks retire it, by handing back `afe_idle`. */
                ESP_LOGW(TAG, "playback: capture did not yield the codec");
                continue;
            }
            xSemaphoreTake(a.lock, portMAX_DELAY);
            /* Re-verify rather than trusting the token. The hand-off is now
             * signalled under the lock so a stale one should be impossible, but
             * this is the assertion that keeps the two directions from ever
             * being open at once — and it costs two loads. If the state does
             * not match, the real acknowledgement is still coming: drop this
             * chunk and let the next cycle re-request. */
            if (a.mode != UBO_AUDIO_PLAYING || a.in_open) {
                ESP_LOGW(TAG, "playback: stale codec hand-off, retrying");
                xSemaphoreGive(a.lock);
                continue;
            }
        }
#endif
        if (n > 0) {
            /* Audio resuming after a gap with the codec still open means the
             * ring was starved mid-utterance -- measured on resume so the
             * silence after a finished utterance is not counted. */
            const int64_t resumed_us = esp_timer_get_time();
            if (a.out_open && a.last_feed_us &&
                resumed_us - a.last_feed_us > 100000) {
                a.underruns++;
                if (a.underruns == 1 || a.underruns % 5 == 0) {
                    ESP_LOGW(TAG,
                             "playback: %u underrun(s), ring starved for %lld ms",
                             a.underruns,
                             (long long)((resumed_us - a.last_feed_us) / 1000));
                }
            }
            if (!a.out_open || a.out_rate != a.want_rate ||
                a.out_ch != a.want_ch || a.out_width != a.want_width) {
                close_out();
                open_out(a.want_rate, a.want_ch, a.want_width, a.want_vol);
            }
            if (a.out_open) {
                apply_gain(buf, n);
                esp_codec_dev_write(a.out_dev, buf, (int)n);
                a.last_feed_us = esp_timer_get_time();
            }
        } else if (a.out_open &&
                   esp_timer_get_time() - a.last_feed_us > PLAY_IDLE_CLOSE_US) {
            close_out();
#ifdef CONFIG_UBO_WAKE_ENABLE
            a.wake_resume_at_us =
                esp_timer_get_time() + CONFIG_UBO_WAKE_COOLDOWN_MS * 1000LL;
#endif
        }
#ifdef CONFIG_UBO_WAKE_ENABLE
        /* Re-arm the wake word once the speaker is shut and the room has had
         * time to go quiet. Only from PLAYING: a talk session owns the codec
         * until the core ends it, and mic_release() re-arms in that case. */
        if (a.mode == UBO_AUDIO_PLAYING && !a.out_open && AFE_ACTIVE &&
            a.wake_active && a.wake_armed && !a.wake_muted &&
            !a.capture_wedged &&
            esp_timer_get_time() >= a.wake_resume_at_us) {
            wake_listen_start();
        }
        /* Local watchdog. A wake session is ended by the core, so if the start
         * action never landed (network down, or the dispatch worker dropped it)
         * nothing local would ever reopen the speaker: ubo_audio_play refuses
         * every chunk while STREAMING, and the microphone stays open. Bound it.
         * Push-to-talk does not need this — releasing the button ends it. */
        if (a.mode == UBO_AUDIO_STREAMING && a.session_started_us &&
            esp_timer_get_time() - a.session_started_us > SESSION_MAX_US) {
            ESP_LOGE(TAG, "session ran %d s with no stop from the core; "
                          "ending it locally",
                     (int)(SESSION_MAX_US / 1000000));
            a.session_started_us = 0;
            a.mic_stop = true;
        }
#endif
        xSemaphoreGive(a.lock);
    }
}

void ubo_audio_play(const uint8_t *pcm, size_t len, int rate, int channels,
                    int width, float volume) {
    if (!a.out_dev || !pcm || len == 0) {
        return;
    }
    /* Only a STREAMING session refuses playback. IDLE_WAKE does not: the wake
     * word yields the codec instead (play_task pauses capture), because
     * otherwise always-on listening would mean the device could never speak. */
    if (MIC_STREAMING()) {
        a.drops_mic_active++;
        if (a.drops_mic_active == 1 || a.drops_mic_active % 25 == 0) {
            ESP_LOGW(TAG, "playback: %u chunk(s) refused, talk session open",
                     a.drops_mic_active);
        }
        return;
    }
    a.want_rate = rate;
    a.want_ch = channels;
    a.want_width = width;
    a.want_vol = volume;
    /* All-or-nothing: a partial write on timeout would split a 16-bit sample
     * and turn the rest of the stream into static. Wait for room (the play
     * task drains in real time; longer than one ~186ms core audio chunk),
     * then drop the WHOLE chunk. Safe as check-then-send: this is the only
     * writer, so free space can only grow in between. */
    const TickType_t deadline = xTaskGetTickCount() + pdMS_TO_TICKS(300);
    while (xStreamBufferSpacesAvailable(a.play_ring) < len) {
        if (xTaskGetTickCount() >= deadline) {
            /* The ring drains at playback rate, so this fires when the core
             * delivers an utterance faster than real time: the excess has
             * nowhere to go and this chunk is lost, which is heard as a gap. */
            a.drops_ring_full++;
            if (a.drops_ring_full == 1 || a.drops_ring_full % 10 == 0) {
                ESP_LOGW(
                    TAG,
                    "playback: %u chunk(s) dropped, ring full (want %u B, free %u B)",
                    a.drops_ring_full, (unsigned)len,
                    (unsigned)xStreamBufferSpacesAvailable(a.play_ring));
            }
            return;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    xStreamBufferSend(a.play_ring, pcm, len, 0);
}

void ubo_audio_stop_playback(void) {
    if (!a.play_ring) {
        return;
    }
    a.flush = true; /* the play task resets the ring within one 50ms cycle */
}

/* ── mic capture task: 16k mono frames -> accumulate a chunk -> callback ── */
static uint8_t s_mic_buf[MIC_BUF_BYTES];

/* Hand a finished chunk to the client and reset the accumulator. */
static void mic_emit(size_t *filled) {
    { /* TEMP: checksum + peak per emit. Identical checksums on consecutive
       * emits == stale buffer; varying == content is fine and the fault is
       * downstream of here. Unthrottled: ~6/s is readable and we need every
       * one to compare them. */
        uint32_t sum = 0;
        int32_t pk = 0;
        const int16_t *s16 = (const int16_t *)s_mic_buf;
        for (size_t i = 0; i < *filled / sizeof(int16_t); i++) {
            sum = sum * 31u + (uint32_t)(uint16_t)s16[i];
            const int32_t v = s16[i] < 0 ? -s16[i] : s16[i];
            if (v > pk) { pk = v; }
        }
        ESP_LOGW(TAG, "emit %u B peak %ld sum %08x", (unsigned)*filled, (long)pk,
                 (unsigned)sum);
        /* TEMP: every ~3s dump one chunk as base64 so the host can rebuild a
         * WAV and we can actually LISTEN to what the device is sending. */
        /* Skip the first emits: AFE's ring is still filling and fetch returns
         * cold-start contents, which is NOT representative of steady state.
         * Dumping emit #1 made every earlier analysis wrong. */
    }
#ifdef CONFIG_UBO_MIC_SESSION_RECORDER
    if (a.rec_buf && a.rec_len + *filled <= a.rec_cap) {
        memcpy(a.rec_buf + a.rec_len, s_mic_buf, *filled);
        a.rec_len += *filled;
    }
#endif
    if (a.mic_cb) {
        a.mic_cb(a.mic_user, s_mic_buf, *filled,
                 (float)(esp_timer_get_time() / 1000000.0));
    }
    *filled = 0;
}

#ifdef CONFIG_UBO_MIC_SESSION_RECORDER
/* Emit the recorded session as base64 once capture has stopped. Debug aid,
 * off by default -- see UBO_MIC_SESSION_RECORDER in Kconfig.projbuild for what
 * it is for and why leaving it on makes the device deaf to TTS. */
static void rec_dump(void) {
    if (!a.rec_buf || a.rec_len == 0) {
        return;
    }
    ESP_LOGW(TAG, "SESBEGIN %u bytes, 16000 Hz mono s16le", (unsigned)a.rec_len);
    static unsigned char line[1400];
    for (size_t off = 0; off < a.rec_len; off += 1023) {
        const size_t take = (a.rec_len - off) < 1023 ? (a.rec_len - off) : 1023;
        size_t ol = 0;
        if (mbedtls_base64_encode(line, sizeof(line), &ol, a.rec_buf + off,
                                  take) == 0) {
            ESP_LOGW(TAG, "SES %.*s", (int)ol, (const char *)line);
        }
        vTaskDelay(1); /* let the USB console drain; we are off the clock here */
    }
    ESP_LOGW(TAG, "SESEND");
    a.rec_len = 0;
}
#endif /* CONFIG_UBO_MIC_SESSION_RECORDER */

/* Release the codec once capture has finished (both AFE tasks and the plain
 * path funnel through here so the teardown is identical). */
static void mic_release(void) {
#ifdef CONFIG_UBO_AFE_ENABLE
    /* Reported regardless of the recorder: this is mic audio the device failed
     * to capture, which no other counter covers. */
    if (a.mic_dropped) {
        ESP_LOGE(TAG, "capture ring overflow: %u bytes dropped",
                 (unsigned)a.mic_dropped);
        a.mic_dropped = 0;
    }
#endif
#ifdef CONFIG_UBO_MIC_SESSION_RECORDER
    /* Deliberately ahead of leaving STREAMING: the dump describes the session
     * that is ending, and capture must stay shut while it drains. The cost is
     * that playback is refused meanwhile -- acceptable only because this is a
     * debug build. */
    rec_dump();
#endif
    xSemaphoreTake(a.lock, portMAX_DELAY);
    close_in();
    /* PLAYING means "the codec is free", not "audio is playing" — it is the
     * state the speaker can claim without asking anyone. With a wake word
     * configured, play_task re-arms listening from here once the cooldown has
     * elapsed; that keeps every entry into IDLE_WAKE in one place instead of
     * racing this teardown against an incoming TTS chunk. */
    a.mode = UBO_AUDIO_PLAYING;
#ifdef CONFIG_UBO_WAKE_ENABLE
    a.session_started_us = 0; /* the watchdog has nothing left to watch */
    a.wedge_count = 0;        /* reached here, so the hand-off worked */
    a.wake_resume_at_us =
        esp_timer_get_time() + CONFIG_UBO_WAKE_COOLDOWN_MS * 1000LL;
#endif
    xSemaphoreGive(a.lock);
}

#ifdef CONFIG_UBO_AFE_ENABLE
/* ── AFE path ──
 * Two tasks, mirroring esp-sr's own reference design: `ubo_feed` blocks on the
 * codec and hands raw interleaved mic frames to AFE, `ubo_mic` blocks on AFE
 * and forwards the enhanced single channel. Splitting them decouples the two
 * blocking waits — a single task would have to finish AFE's processing latency
 * before returning to the codec, and the capture DMA would overrun.
 *
 * Note we do NOT act on AFE's VAD: ubo-core owns turn detection and drives
 * AssistantStopListeningAction. The device only ever streams what it hears. */
static void afe_feed_task(void *arg) {
    (void)arg;
    const int chunk = a.afe->get_feed_chunksize(a.afe_data);
    const int nch = a.afe->get_feed_channel_num(a.afe_data);
    /* Internal RAM, allocated once at afe_setup(). esp-sr consumes this pointer
     * in its DSP and every upstream example allocates it MALLOC_CAP_INTERNAL;
     * a PSRAM buffer left AFE's ring permanently empty. Allocating at boot
     * rather than here is what makes internal RAM affordable. */
    const size_t bytes = a.afe_feed_bytes;
    int16_t *buf = a.afe_feed_buf;
    int16_t *mic = a.afe_mic_buf;
    const size_t mic_bytes = a.afe_mic_bytes;
    size_t cap_bytes = 0;
    int64_t cap_t0 = 0;
    for (;;) {
    xSemaphoreTake(a.afe_go_feed, portMAX_DELAY);
    cap_bytes = 0;
    cap_t0 = esp_timer_get_time();
    /* CAPTURE_RUNNING(): `mic_stop` ends the session, `capture_pause` only
     * yields the hardware to the speaker. esp_codec_dev_read() blocks for at
     * most one feed chunk (~32ms), so either exits promptly and neither needs
     * the read aborted. */
    while (CAPTURE_RUNNING()) {
        int rr = esp_codec_dev_read(a.in_dev, mic, (int)mic_bytes);
        if (rr != 0) {
            ESP_LOGW(TAG, "codec read failed: %d", rr);
            break;
        }
        cap_bytes += mic_bytes;
        /* Interleave the microphones into AFE's wider frame, zeroing every
         * channel the codec does not supply (the playback reference). Walking
         * backwards is not needed here because source and destination are
         * different buffers. */
        for (int i = 0; i < chunk; i++) {
            for (int c = 0; c < nch; c++) {
                buf[i * nch + c] =
                    (c < AFE_MIC_CHANNELS) ? mic[i * AFE_MIC_CHANNELS + c] : 0;
            }
        }
        /* Diagnostic: is the codec actually giving us 2ch audio, in real time?
         * Suppressed while merely listening for the wake word — capture is
         * always-on there, so an unconditional line a second would be a
         * permanent console flood rather than a per-session observation. */
        if (MIC_STREAMING()) {
            static int64_t t; const int64_t now = esp_timer_get_time();
            if (now - t > 1000000) { t = now;
                const double el = (double)(now - cap_t0) / 1000000.0;
                ESP_LOGW(TAG, "capture realtime: %.0f%% (%.2fs audio in %.2fs)",
                         el > 0 ? (double)cap_bytes / (double)(MIC_RATE * AFE_MIC_CHANNELS * 2) / el * 100.0 : 0.0,
                         (double)cap_bytes / (double)(MIC_RATE * AFE_MIC_CHANNELS * 2), el);
                int32_t pk0 = 0, pk1 = 0;
                for (int i = 0; i < chunk; i++) {
                    int32_t v0 = buf[i*nch] < 0 ? -buf[i*nch] : buf[i*nch];
                    int32_t v1 = nch > 1 ? (buf[i*nch+1] < 0 ? -buf[i*nch+1] : buf[i*nch+1]) : 0;
                    if (v0 > pk0) { pk0 = v0; }
                    if (v1 > pk1) { pk1 = v1; }
                }
                ESP_LOGW(TAG, "feed: %u B/read, mic0 peak %ld, mic1 peak %ld",
                         (unsigned)bytes, (long)pk0, (long)pk1);
            }
        }
        a.afe->feed(a.afe_data, buf);
    }
    if (!CAPTURE_PAUSED()) {
        /* Unblock the fetch task if we exited on error. Deliberately NOT done
         * for a pause, which is a hardware hand-off and not the end of
         * anything: promoting it to `mic_stop` would send the fetch task down
         * the session-teardown path instead of parking for a re-arm.
         * (Only IDLE_WAKE is ever paused — a STREAMING session refuses playback
         * outright, so nothing asks it for the codec.) */
        a.mic_stop = true;
    }
    /* Tell the fetch task we are out of esp_codec_dev_read() so it is safe to
     * close the capture device. Without this the codec can be closed while this
     * task is still blocked inside it. */
    xSemaphoreGive(a.afe_feed_idle);
    }
}

static void afe_fetch_task(void *arg) {
    (void)arg;
    /* Pull enhanced audio from AFE and hand it upstream in the same ~200ms
     * chunks the plain capture path uses. The dispatch cost, not the chunk
     * size, sets the ceiling here — see the accumulation loop below. */
    const size_t chunk_target = (size_t)CONFIG_UBO_MIC_CHUNK_MS * MIC_BYTES_PER_MS;
    size_t filled = 0;
    for (;;) {
    xSemaphoreTake(a.afe_go_fetch, portMAX_DELAY);
    filled = 0; /* never carry a partial chunk across sessions */
    { /* TEMP: AFE's own view of its geometry, rather than our assumption. */
        static bool once;
        if (!once) { once = true;
            ESP_LOGW(TAG,
                     "AFE geom: feed %d smp/%d ch, fetch %d smp/%d ch, "
                     "chan %d, rate %d",
                     a.afe->get_feed_chunksize(a.afe_data),
                     a.afe->get_feed_channel_num(a.afe_data),
                     a.afe->get_fetch_chunksize(a.afe_data),
                     a.afe->get_fetch_channel_num(a.afe_data),
                     a.afe->get_channel_num(a.afe_data),
                     a.afe->get_samp_rate(a.afe_data));
        }
    }
    while (CAPTURE_RUNNING()) {
        afe_fetch_result_t *res =
            a.afe->fetch_with_delay(a.afe_data, pdMS_TO_TICKS(100));
        if (!res || res->ret_value != 0 || res->data_size <= 0) {
            continue;
        }
#ifdef CONFIG_UBO_WAKE_ENABLE
        /* Compare against WAKENET_DETECTED explicitly: wakeup_state also takes
         * WAKENET_CHANNEL_VERIFIED (-1), so a `!= WAKENET_NO_DETECT` test would
         * fire on channel verification too. */
        if (res->wakeup_state == WAKENET_DETECTED) {
            ESP_LOGW(TAG, "WAKE: \"%s\" word=%d model=%d ch=%d",
                     a.wake_phrase ? a.wake_phrase : "?", res->wake_word_index,
                     res->wakenet_model_index, res->trigger_channel_id);
            /* Decide ENTIRELY under a.lock. Testing `mode` outside it and then
             * taking the lock to write left a window where play_task could
             * request a pause in between: we would promote to STREAMING, tell
             * the core a turn had started, and then be torn down by our own
             * teardown path a moment later — leaving the core with a session
             * that never receives a sample.
             *
             * play_task makes its pause decision under the same lock, so with
             * both sides holding it the two are mutually exclusive: either we
             * promote and play_task then sees STREAMING and backs off, or
             * `capture_pause` is already set and we decline this detection.
             *
             * Conditions:
             *  - `wake_armed`: a client is connected and bound. Nothing else
             *    ever ends a wake session — the stop comes from the core, in
             *    reply to the action this callback dispatches — so promoting
             *    without one would wedge STREAMING forever.
             *  - IDLE_WAKE only: mid-session the core owns the turn, and
             *    hearing the wake word inside a reply must not restart it.
             *  - past the cooldown, and not paused. */
            bool promoted = false;
            xSemaphoreTake(a.lock, portMAX_DELAY);
            if (a.wake_armed && a.wake_cb && !a.wake_muted &&
                !a.capture_pause && a.mode == UBO_AUDIO_IDLE_WAKE &&
                esp_timer_get_time() >= a.wake_resume_at_us) {
                /* Promote BEFORE telling the core, so the speech that follows
                 * the wake word is already buffering while the dispatch is in
                 * flight — otherwise the first word or two of every utterance
                 * is lost to the round trip. The callbacks come from wake_bind
                 * for the same reason. */
                a.mic_cb = a.wake_mic_cb;
                a.mic_user = a.wake_mic_user;
                a.mode = UBO_AUDIO_STREAMING;
                a.session_started_us = esp_timer_get_time();
                promoted = true;
            }
            xSemaphoreGive(a.lock);
            if (promoted) {
                a.wake_cb(a.wake_user, a.wake_phrase ? a.wake_phrase : "");
            }
        }
        /* While only listening for the wake word, the enhanced audio is
         * processed and discarded — AFE still has to see every sample for
         * WakeNet to work, but nothing goes to the core until a session opens.
         * Deliberately after the wake check above and before the accumulator,
         * so `filled` stays at zero and the first chunk of a session begins at
         * the moment the session begins.
         *
         * Inside the ifdef because without a wake word this loop only ever runs
         * during a session, making the test dead code. */
        if (!MIC_STREAMING()) {
            continue;
        }
#endif
        const size_t n = (size_t)res->data_size;
        /* Accumulate into the same ~200ms chunk the plain capture path uses.
         * Emitting each AFE chunk on its own looks harmless (32ms of audio) but
         * every dispatch is a full unary POST costing ~400ms, so the callback
         * became the bottleneck: measured coverage was 3% — 1.44s of audio
         * delivered across 47.7s of speech, the rest dropped while AFE kept
         * producing. Upstream STT cannot transcribe a stream with 92% missing.
         * Copy with clamping so a chunk that straddles the buffer end splits
         * instead of wedging below the emit threshold. */
        const uint8_t *src = (const uint8_t *)res->data;
        size_t left = n;
        while (left > 0) {
            const size_t space = MIC_BUF_BYTES - filled;
            const size_t take = left < space ? left : space;
            memcpy(s_mic_buf + filled, src, take);
            filled += take;
            src += take;
            left -= take;
            if (filled >= chunk_target || filled == MIC_BUF_BYTES) {
#ifdef CONFIG_UBO_MIC_SESSION_RECORDER
                if (a.rec_buf && a.rec_len + filled <= a.rec_cap) {
                    memcpy(a.rec_buf + a.rec_len, s_mic_buf, filled);
                    a.rec_len += filled;
                }
#endif
                /* Non-blocking by design: never make capture wait on the net. */
                const size_t sent =
                    xStreamBufferSend(a.mic_ring, s_mic_buf, filled, 0);
                a.mic_dropped += filled - sent;
                filled = 0;
            }
        }
    }
    /* Wait for the feed task to leave the codec before closing it. This barrier
     * is the whole reason the codec is safe to close here, so a timeout must
     * NOT fall through to closing it — that would pull the device out from
     * under an in-flight esp_codec_dev_read(). Force feed out instead and let
     * the next arm start clean. */
    if (xSemaphoreTake(a.afe_feed_idle, pdMS_TO_TICKS(500)) != pdTRUE) {
        /* Force feed out and wait again. It re-tests the loop condition once
         * per chunk (~32ms), so this succeeds unless esp_codec_dev_read itself
         * is wedged. */
        ESP_LOGW(TAG, "feed still holds the codec; forcing it out");
        a.mic_stop = true;
        if (xSemaphoreTake(a.afe_feed_idle, pdMS_TO_TICKS(1000)) != pdTRUE) {
            /* The read is stuck in the driver. Do NOT close the device under
             * it. Release play_task rather than livelocking it on a handover
             * that will never complete, and park; audio is degraded from here
             * but the rest of the device keeps running and the log says why. */
            ESP_LOGE(TAG, "feed did not leave the codec; capture is wedged");
            xSemaphoreTake(a.lock, portMAX_DELAY);
            a.mode = UBO_AUDIO_PLAYING;
#ifdef CONFIG_UBO_WAKE_ENABLE
            /* Once latched, `capture_wedged` keeps the re-arm gate shut. It has
             * to: the capture device is still open, so the gate would otherwise
             * pass and put us back into IDLE_WAKE with a feed task that reads
             * nothing — "the wake word silently stopped working", plus an error
             * per TTS chunk.
             *
             * But COUNT rather than latch on the first failure. 1.5s of silence
             * from feed means it is stuck in the driver OR merely frozen — a
             * flash erase suspends the other core, and a chained NVS commit can
             * plausibly outlast the window. Feed recovers from that by itself,
             * and any clean hand-off resets the count. */
            if (++a.wedge_count >= 3) {
                a.capture_wedged = true;
            }
            a.capture_pause = false;
            a.session_started_us = 0;
            xSemaphoreGive(a.afe_idle); /* inside the lock; see the pause branch */
#endif
            xSemaphoreGive(a.lock);
            continue;
        }
    }
#ifdef CONFIG_UBO_WAKE_ENABLE
    if (CAPTURE_PAUSED()) {
        /* Yielding to the speaker, not ending a session. Close the microphone
         * and tell play_task the codec is its to open. Both tasks then park on
         * their start semaphores until play_task re-arms listening. */
        xSemaphoreTake(a.lock, portMAX_DELAY);
        close_in();
        a.mode = UBO_AUDIO_PLAYING;
        /* Retire the request HERE, where it is honoured — not at the next
         * re-arm. The re-arm cannot run while the speaker holds the codec, so
         * leaving the flag set left it latched for the whole reply, and any
         * mic_start in that window (a BOOT hold to interrupt, i.e. the only way
         * to interrupt at all) would stall and then give up.
         *
         * Safe against the hazard this flag exists to prevent: the
         * afe_feed_idle barrier above has already confirmed the feed task is
         * out of esp_codec_dev_read() and parked on afe_go_feed, so clearing it
         * cannot put feed back into the codec — only a semaphore give can. */
        a.capture_pause = false;
        a.wedge_count = 0; /* a clean hand-off: whatever stalled us is over */
        /* Signal INSIDE the lock, together with the state it is acknowledging.
         * Given outside, this token could be handed over after play_task had
         * already re-armed listening and issued a SECOND pause request — whose
         * 0-tick drain (also under the lock) had therefore found nothing to
         * drop. play_task would then take this stale token as the answer to the
         * new request and open the speaker while the microphone was open and
         * feed was mid-read. Not caught by the driver's rate check either: TTS
         * defaults to 16kHz, the same rate as capture. */
        xSemaphoreGive(a.afe_idle);
        xSemaphoreGive(a.lock);
        continue;
    }
#endif
    mic_release();
    }
}
#endif /* CONFIG_UBO_AFE_ENABLE */

#ifdef CONFIG_UBO_AFE_ENABLE
/* Drains the capture ring into the client. This task is allowed to block for
 * as long as the network takes; nothing real-time is waiting behind it. */
static void afe_send_task(void *arg) {
    (void)arg;
    /* PSRAM, not .bss: internal RAM is the scarce resource on this board and
     * this buffer only ever feeds the network. */
    uint8_t *out = heap_caps_malloc(MIC_BUF_BYTES, MALLOC_CAP_SPIRAM);
    if (!out) {
        ESP_LOGE(TAG, "send buffer alloc failed");
        vTaskDelete(NULL);
        return;
    }
    for (;;) {
        const size_t n = xStreamBufferReceive(a.mic_ring, out, MIC_BUF_BYTES,
                                              pdMS_TO_TICKS(100));
        if (n > 0 && a.mic_cb) {
            a.mic_cb(a.mic_user, out, n,
                     (float)(esp_timer_get_time() / 1000000.0));
        }
    }
}
#endif

static void mic_task(void *arg) {
    (void)arg;
    const size_t chunk_target = (size_t)CONFIG_UBO_MIC_CHUNK_MS * MIC_BYTES_PER_MS;
    size_t filled = 0;
    while (!a.mic_stop) {
        int r = esp_codec_dev_read(a.in_dev, s_mic_buf + filled, MIC_FRAME_BYTES);
        if (r != 0) {
            ESP_LOGW(TAG, "codec read failed: %d", r);
            break;
        }
        filled += MIC_FRAME_BYTES;
        if (filled >= chunk_target) {
            mic_emit(&filled);
        }
    }
    mic_release();
    vTaskDelete(NULL);
}

#ifdef CONFIG_UBO_AFE_ENABLE
/* Build the AFE once at init. "MM" is the two ES7210 microphone channels with
 * no playback reference — matching what the codec actually gives us, so unlike
 * esp-sr's own example there is no zero-padded third channel to fake one.
 * AFE_TYPE_VC because ubo-core does the recognition; we only want a cleaner
 * single channel out. Buffers go to PSRAM: internal RAM is the scarce resource
 * here and AFE's are large. Returns 0 on success; a failure is non-fatal, the
 * caller falls back to raw capture. */
static int afe_setup(void) {
    srmodel_list_t *models = NULL;
    char *wn_model = NULL;
#ifdef CONFIG_UBO_WAKE_ENABLE
    /* Reads the `model` partition (mmapped, so the weights cost flash address
     * space rather than RAM — CONFIG_MODEL_IN_FLASH). NULL here is not fatal:
     * afe_config_check() clears wakenet_init when no model name is set and we
     * fall back to the push-to-talk-only pipeline. */
    models = esp_srmodel_init("model");
    if (models) {
        /* An empty CONFIG_UBO_WAKE_MODEL means "whichever wn* model is in the
         * partition", which is what we want with a single packed model: a name
         * that matches nothing would resolve to NULL and silently disable the
         * wake word. */
        const char *want = CONFIG_UBO_WAKE_MODEL;
        wn_model = esp_srmodel_filter(models, ESP_WN_PREFIX,
                                      want[0] ? want : NULL);
    }
    if (wn_model) {
        a.wake_phrase = esp_srmodel_get_wake_words(models, wn_model);
    }
    ESP_LOGI(TAG, "wake word: model=%s phrase=\"%s\"",
             wn_model ? wn_model : "(none)",
             a.wake_phrase ? a.wake_phrase : "(none)");
#endif
    /* `models` is consumed here, not just read: with a non-NULL list AFE
     * resolves and loads the wakenet model itself. */
    afe_config_t *cfg = afe_config_init(AFE_INPUT_FORMAT, models, AFE_TYPE_VC,
                                        AFE_MODE_HIGH_PERF);
    if (!cfg) {
        ESP_LOGE(TAG, "afe_config_init failed");
        return -1;
    }
    cfg->aec_init = false;      /* no reference channel wired; see Kconfig */
    /* WakeNet under AFE_TYPE_VC is supported, despite VC being the "voice
     * communication" profile: nothing in afe_config_check() keys wakenet off
     * afe_type — it only clears wakenet_init when no model name is set. VC
     * forces mic_num to 1, which selects the esp_afe_sr_1mic implementation,
     * and that one carries the full wakenet op set (afe_init_wn,
     * afe_wn_run_single_mic, afe_enable_wakenet). So the wake word costs us
     * nothing from the capture configuration that is known to work here.
     *
     * Note WakeNet runs inside fetch(), not feed() — see afe_fetch_task and
     * the core placement of `ubo_mic` in afe_setup's task creation. */
    cfg->wakenet_init = (wn_model != NULL);
    cfg->wakenet_model_name = wn_model;
#ifdef CONFIG_UBO_WAKE_ENABLE
    /* The multi-channel detection modes are not usable here: mic_num is forced
     * to 1 above, so only DET_MODE_90 / DET_MODE_95 apply. (An unset bool
     * Kconfig symbol is undefined rather than 0, hence #ifdef and not a
     * ternary.) */
#ifdef CONFIG_UBO_WAKE_AGGRESSIVE
    cfg->wakenet_mode = DET_MODE_95;
#else
    cfg->wakenet_mode = DET_MODE_90;
#endif
#endif
    /* VAD is enabled for CHANNEL SELECTION, not for turn detection — ubo-core
     * still owns that and we ignore vad_state entirely. With SE(BSS) running,
     * something has to pick which separated source is the speaker:
     * esp_afe_config.h says the output channel is chosen "by wakenet or vad",
     * and with both off the selection stuck on a suppressed source, which AGC
     * then amplified into full-scale noise. That was the entire "BSS outputs a
     * constant" symptom. */
    cfg->vad_init = true;
    cfg->vad_enable_channel_trigger = true;
    /* AGC ON. It was disabled earlier on the theory that it caused output
     * "pinned at a constant peak of 15402" — that turned out to be the SE(BSS)
     * channel, which fetch was selecting regardless of AGC, so the reasoning
     * was invalid. A recorded session measures peak -24 dBFS / rms -41.6 dBFS
     * with no clipping, and the ES7210 is already at its maximum 37.5 dB analog
     * gain, so the missing ~15-20 dB has to come from here. */
    cfg->agc_init = true;
    /* WEBRTC is what we want with no wake word. With one, afe_config_check()
     * overrides this to AFE_AGC_MODE_WAKENET regardless ("wakenet is activated,
     * disable WebRTC AGC.") — stated here so the code says what actually
     * happens. This is the one AFE change a wake word forces on the streamed
     * capture path, so it is where to look first if capture levels regress
     * against the AFE-FAR-FIELD.md baseline. */
    cfg->agc_mode =
        cfg->wakenet_init ? AFE_AGC_MODE_WAKENET : AFE_AGC_MODE_WEBRTC;
    /* CRITICAL. Without this, AFE picks its output channel "by wakenet or vad"
     * (esp_afe_config.h) — and this was originally written when both were
     * disabled, because ubo-core owns turn detection and the wake word had not
     * landed. Nothing then
     * drove the selection: trigger_channel_id came out as 2, and fetch returned
     * raw_data channel 2, a channel with no microphone behind it. That is the
     * entire "output is noise with a constant peak" symptom — the microphone
     * channels (raw_data ch0/ch1) were clean speech the whole time. */
    /* Must be false, or the output is pinned to a raw microphone channel and
     * the BSS result is discarded — i.e. no far-field processing at all. */
    cfg->fixed_output_channel = false;
    /* SE(BSS) OFF. fetch's `data` was proven byte-identical to raw_data
     * channel 2 (500/500 samples, two independent runs), and raw_data is
     * [mic0, mic1, SE-output] — so the noise we were streaming IS the blind
     * source separation output, while both microphone channels were clean
     * speech throughout. afe_config_check() prioritises SE over NS on
     * two-microphone input, so SE has to go for NS to run at all; per
     * esp_afe_config.h, with SE deactivated AFE "will only use the first
     * microphone channel", which is exactly the clean signal we want. */
    /* SE(BSS) is the far-field algorithm: it separates the talker from the
     * rest of the room across the two microphones. It requires AFE_TYPE_SR —
     * AFE_TYPE_VC "only support single microphone channel", and for a single
     * channel the library deactivates SE outright. */
    cfg->se_init = false;
    /* NS off: the library warns it "may reduce the accuracy of speech
     * recognition", and config_check prioritises SE over NS for two-mic input
     * anyway. */
    cfg->ns_init = true;
    cfg->memory_alloc_mode = AFE_MEMORY_ALLOC_MORE_PSRAM;
    /* TEMP: afe_config_check() is documented to MODIFY the config on conflict.
     * fetch reports raw_data_channels=3 while we feed 2 — print what AFE
     * actually settled on rather than what we asked for. */
    ESP_LOGW(TAG, "pcm_config BEFORE check: total=%d mic=%d ref=%d rate=%d",
             cfg->pcm_config.total_ch_num, cfg->pcm_config.mic_num,
             cfg->pcm_config.ref_num, cfg->pcm_config.sample_rate);
    afe_config_check(cfg);
    ESP_LOGW(TAG, "pcm_config AFTER  check: total=%d mic=%d ref=%d rate=%d "
                  "fixed_out=%d out_playback=%d se=%d ns=%d wakenet=%d",
             cfg->pcm_config.total_ch_num, cfg->pcm_config.mic_num,
             cfg->pcm_config.ref_num, cfg->pcm_config.sample_rate,
             (int)cfg->fixed_output_channel, (int)cfg->output_playback_channel,
             (int)cfg->se_init, (int)cfg->ns_init, (int)cfg->wakenet_init);
    /* Read AFTER the check: it clears wakenet_init when no model resolved, and
     * that is the difference between "listening" and "silently push-to-talk
     * only". Everything downstream keys off this, not off the Kconfig symbol. */
    const bool wakenet_live = cfg->wakenet_init;

    a.afe = esp_afe_handle_from_config(cfg);
    if (a.afe) {
        a.afe_data = a.afe->create_from_config(cfg);
    }
    afe_config_free(cfg);
    if (!a.afe || !a.afe_data) {
        ESP_LOGE(TAG, "AFE create failed; falling back to raw capture");
        a.afe = NULL;
        a.afe_data = NULL;
        return -1;
    }
    /* Prints the algorithm chain AFE actually built. The one line that proves
     * the wake word is live: it contains "WakeNet(<model>,...)". */
    a.afe->print_pipeline(a.afe_data);
    if (!wakenet_live) {
        a.wake_phrase = NULL;
    }
    /* NB: `a.wake_active` is deliberately NOT set here. Everything below can
     * still fail, and those paths null `a.afe_data` while leaving `a.afe`
     * set — so an early `wake_active` would let play_task arm listening and
     * call `a.afe->reset_buffer(NULL)`. It is asserted at the very end of this
     * function instead, once the front end is genuinely usable. */
/* Nested rather than relying on the preprocessor treating the undefined symbol
 * as 0 when the wake word is compiled out. */
#ifdef CONFIG_UBO_WAKE_ENABLE
#if CONFIG_UBO_WAKE_THRESHOLD_PCT > 0
    if (wakenet_live) {
        /* Model index is 1-based; we only ever load one. */
        const int tr = a.afe->set_wakenet_threshold(
            a.afe_data, 1, CONFIG_UBO_WAKE_THRESHOLD_PCT / 100.0f);
        ESP_LOGI(TAG, "wake threshold override %d%% rc=%d",
                 CONFIG_UBO_WAKE_THRESHOLD_PCT, tr);
    }
#endif
#endif
    /* Allocate the feed buffer HERE, at boot, from INTERNAL RAM. esp-sr's DSP
     * consumes this pointer directly and every upstream example allocates it
     * MALLOC_CAP_INTERNAL; handing it PSRAM left AFE's ringbuffer permanently
     * empty ("Ringbuffer of AFE is empty") and fetch returning a fixed
     * artifact. It cannot be allocated in the feed task because only ~6KB of
     * internal RAM is free once a talk session starts. */
    a.afe_mic_bytes = (size_t)a.afe->get_feed_chunksize(a.afe_data) *
                      AFE_MIC_CHANNELS * sizeof(int16_t);
    a.afe_mic_buf =
        heap_caps_malloc(a.afe_mic_bytes, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (!a.afe_mic_buf) {
        ESP_LOGE(TAG, "AFE mic buffer (%u B internal) failed",
                 (unsigned)a.afe_mic_bytes);
        a.afe_data = NULL;
        return -1;
    }
    a.afe_feed_bytes = (size_t)a.afe->get_feed_chunksize(a.afe_data) *
                       a.afe->get_feed_channel_num(a.afe_data) * sizeof(int16_t);
    a.afe_feed_buf = heap_caps_malloc(a.afe_feed_bytes,
                                      MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (!a.afe_feed_buf) {
        ESP_LOGE(TAG, "AFE feed buffer (%u B internal) failed",
                 (unsigned)a.afe_feed_bytes);
        a.afe_data = NULL;
        return -1;
    }
    a.mic_ring = xStreamBufferCreateWithCaps(256 * 1024, 1, MALLOC_CAP_SPIRAM);
    a.afe_go_feed = xSemaphoreCreateBinary();
    a.afe_go_fetch = xSemaphoreCreateBinary();
    a.afe_feed_idle = xSemaphoreCreateBinary();
#ifdef CONFIG_UBO_WAKE_ENABLE
    a.afe_idle = xSemaphoreCreateBinary();
    if (!a.afe_idle) {
        ESP_LOGE(TAG, "AFE idle semaphore alloc failed");
        a.afe_data = NULL;
        return -1;
    }
#endif
    /* Create both tasks NOW and park them on their start semaphores, with their
     * stacks in PSRAM. Creating them per-session was the actual defect behind
     * every "AFE returns a constant" symptom: by talk time only ~3KB of
     * internal RAM remains, xTaskCreate failed silently as far as the audio
     * path was concerned, and fetch() went on returning the ring's stale
     * contents. Creating them at boot from INTERNAL RAM is not an alternative
     * — 16KB there starves the client and input tasks and the UI never
     * starts. */
    if (!a.mic_ring || !a.afe_go_feed || !a.afe_go_fetch || !a.afe_feed_idle ||
        xTaskCreatePinnedToCoreWithCaps(afe_send_task, "ubo_send",
                                        AFE_TASK_STACK, NULL, 5, NULL, 0,
                                        MALLOC_CAP_SPIRAM) != pdPASS ||
        /* Fetch is on core 1 with the wake word, core 0 without it.
         *
         * WakeNet's inference runs inside fetch_with_delay(), not inside feed()
         * — so with a wake word this task carries a neural network CONTINUOUSLY,
         * and core 0 is where WiFi and lwIP live. Core 1 keeps that load off the
         * network path; feed still preempts it there at priority 7, so the
         * capture DMA is protected exactly as before.
         *
         * Without a wake word, fetch is idle between sessions and the original
         * split (fetch on 0, feed alone on 1) is left untouched. */
        xTaskCreatePinnedToCoreWithCaps(afe_fetch_task, "ubo_mic",
                                        AFE_TASK_STACK, NULL, 6, NULL,
                                        AFE_FETCH_CORE,
                                        MALLOC_CAP_SPIRAM) != pdPASS ||
        /* Feed goes on core 1, at a higher priority, DELIBERATELY away from the
         * network. Both were on core 0 — which also carries WiFi and lwIP — so
         * every blocking dispatch in the fetch task starved this one, the I2S
         * DMA overran, and those samples were lost at the microphone rather
         * than merely delayed. That is what "Ringbuffer of AFE is empty"
         * (an underrun, not an overflow) was reporting, and it cost ~30% of
         * every utterance. Capture is the one thing here that cannot be
         * retried, so it gets the quiet core. */
        xTaskCreatePinnedToCoreWithCaps(afe_feed_task, "ubo_feed",
                                        AFE_TASK_STACK, NULL, 7, NULL, 1,
                                        MALLOC_CAP_SPIRAM) != pdPASS) {
        ESP_LOGE(TAG, "AFE task creation failed (internal free %u)",
                 (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
        a.afe_data = NULL;
        return -1;
    }
    ESP_LOGI(TAG, "AFE ready: feed %d ch x %d samples, internal free %u",
             a.afe->get_feed_channel_num(a.afe_data),
             a.afe->get_feed_chunksize(a.afe_data),
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
    /* Only now, past every failure return: the buffers exist, the tasks exist,
     * and `a.afe_data` is live. This is the flag play_task arms listening on,
     * so setting it any earlier turns a documented, survivable internal-RAM
     * shortage ("falling back to raw capture") into a null dereference. */
    a.wake_active = wakenet_live;
    return 0;
}
#endif

void ubo_audio_mic_start(ubo_audio_mic_cb cb, void *user) {
    if (!a.in_dev) {
        return;
    }
    xSemaphoreTake(a.lock, portMAX_DELAY);
    if (MIC_STREAMING()) {
        /* Idempotent: the core echoes AssistantRequestMicStreamEvent at a
         * session this device started itself. */
        xSemaphoreGive(a.lock);
        return;
    }
#ifdef CONFIG_UBO_WAKE_ENABLE
    if (a.wake_muted) {
        /* The hardware mute switch outranks every caller, local or remote.
         * Without this a BOOT press (or a core-initiated stream request) would
         * reopen the microphone straight through an engaged switch. */
        ESP_LOGW(TAG, "mic start refused: hardware mute engaged");
        xSemaphoreGive(a.lock);
        return;
    }
    /* A pause may be in flight: play_task has asked the capture tasks to yield
     * the codec and is waiting for them, but they have not landed in PLAYING
     * yet. Promoting to STREAMING in that window is lost — the tasks are
     * already unwinding and would tear the session straight back down, leaving
     * the core with a session that never receives a sample. Let the handshake
     * finish instead; both states it can land in are handled below.
     *
     * Safe to block: this runs on the dispatch worker, which is allowed to
     * wait. The bound must exceed the teardown's own worst case — one feed
     * chunk (~32ms) plus the afe_feed_idle barrier, which is 500ms plus a
     * 1000ms forced retry — so 2s. */
    for (int i = 0; i < 200 && CAPTURE_PAUSED(); i++) {
        xSemaphoreGive(a.lock);
        vTaskDelay(pdMS_TO_TICKS(10));
        xSemaphoreTake(a.lock, portMAX_DELAY);
    }
    if (CAPTURE_PAUSED()) {
        /* Never settled. Opening anything now would race the teardown, so
         * decline: the core sees a session that receives no audio and ends it
         * on its own silence timeout, which is self-healing. Forcing it would
         * not be. */
        ESP_LOGE(TAG, "mic start abandoned: capture pause never settled");
        xSemaphoreGive(a.lock);
        return;
    }
    if (a.mode == UBO_AUDIO_IDLE_WAKE) {
        /* Already capturing for the wake word — promoting that to a streaming
         * session is a single state change. No codec churn, no AFE reset, no
         * cold start, and deliberately NO reset_buffer(): what AFE is holding
         * is the run-up to the wake word, and keeping it is what stops a turn
         * from losing its first syllables. */
        a.mic_cb = cb;
        a.mic_user = user;
        a.mode = UBO_AUDIO_STREAMING;
        a.session_started_us = esp_timer_get_time();
        xSemaphoreGive(a.lock);
        return;
    }
#endif
    close_out(); /* free the codec from any playback session first */
    if (open_in() != 0) {
        xSemaphoreGive(a.lock);
        return;
    }
    ESP_LOGW(TAG, "mic open: internal free %u, DMA-capable free %u",
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_DMA));
    a.mic_cb = cb;
    a.mic_user = user;
    a.mic_stop = false;
#ifdef CONFIG_UBO_WAKE_ENABLE
    /* `capture_pause` is already known clear — the wait above either settled it
     * or returned. Start the capture tasks from a known semaphore state for the
     * same reason wake_listen_start does: a stale afe_feed_idle token would
     * make the next teardown skip its barrier. */
    xSemaphoreTake(a.afe_feed_idle, 0);
    xSemaphoreTake(a.afe_go_feed, 0);
    xSemaphoreTake(a.afe_go_fetch, 0);
    /* `afe_idle` too, for symmetry with wake_listen_start. Not strictly needed
     * — a token left here is unreachable, because the only reader is
     * play_task's pause block and that is gated on IDLE_WAKE, which only
     * wake_listen_start can enter (and it drains) — but the arm paths reading
     * the same is worth more than the argument. */
    xSemaphoreTake(a.afe_idle, 0);
    a.session_started_us = esp_timer_get_time();
#endif
    a.mode = UBO_AUDIO_STREAMING;
    xSemaphoreGive(a.lock);
#ifdef CONFIG_UBO_AFE_ENABLE
    /* NB: a.lock was released above; the failure path re-takes it, matching the
     * plain-capture path below. */
    if (AFE_ACTIVE) {
        a.afe->reset_buffer(a.afe_data); /* drop the previous session's tail */
        /* Both tasks already exist and are parked (see afe_setup). Release the
         * fetch task first so it is waiting on AFE before any data arrives. */
        xSemaphoreGive(a.afe_go_fetch);
        xSemaphoreGive(a.afe_go_feed);
        return;
    }
#endif
    if (xTaskCreate(mic_task, "ubo_mic", MIC_TASK_STACK, NULL, 6, NULL) !=
        pdPASS) {
        /* Task stacks must come out of INTERNAL RAM — PSRAM does not count,
         * so a 16MB "free heap" says nothing here. Log what actually matters. */
        ESP_LOGE(TAG,
                 "mic task creation failed (internal free %u, largest block %u)",
                 (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
                 (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL));
        xSemaphoreTake(a.lock, portMAX_DELAY);
        a.mode = UBO_AUDIO_PLAYING;
        close_in();
        xSemaphoreGive(a.lock);
    }
}

void ubo_audio_mic_stop(void) {
    a.mic_stop = true; /* the capture task tears down and clears `mode` */
}

void ubo_audio_wake_set_muted(bool muted) {
#ifdef CONFIG_UBO_WAKE_ENABLE
    xSemaphoreTake(a.lock, portMAX_DELAY);
    if (muted != a.wake_muted) {
        ESP_LOGI(TAG, "wake word %s (hardware mute)",
                 muted ? "muted" : "unmuted");
    }
    a.wake_muted = muted;
    if (muted && a.mode == UBO_AUDIO_IDLE_WAKE) {
        /* Reuse the speaker's pause path: the capture tasks notice within one
         * feed chunk (~32ms), close the microphone and park. play_task will not
         * re-arm while `wake_muted` is set, so it simply stays closed until the
         * switch is released. The afe_idle token this leaves behind is drained
         * by play_task before its next request. */
        a.capture_pause = true;
    } else if (muted && a.mode == UBO_AUDIO_STREAMING) {
        /* Muting mid-turn ENDS the turn rather than pausing it. A pause would
         * keep the session open with the microphone shut, which is a worse lie
         * than either honest option; ending it closes the microphone and lets
         * the core tear the session down. The switch has to actually stop
         * capture — that is the whole point of a hardware mute. */
        a.mic_stop = true;
    }
    xSemaphoreGive(a.lock);
#else
    (void)muted;
#endif
}

void ubo_audio_wake_bind(ubo_audio_wake_cb cb, void *user,
                         ubo_audio_mic_cb mic_cb, void *mic_user) {
#ifdef CONFIG_UBO_WAKE_ENABLE
    xSemaphoreTake(a.lock, portMAX_DELAY);
    a.wake_cb = cb;
    a.wake_user = user;
    a.wake_mic_cb = mic_cb;
    a.wake_mic_user = mic_user;
    /* Arming here, and only here, is what keeps the microphone shut until a
     * client exists to route a turn to — and, on a board that boots into its
     * captive portal, shut for as long as it stays there. */
    a.wake_armed = (cb != NULL);
    xSemaphoreGive(a.lock);
    ESP_LOGI(TAG, "wake word %s (%s)", a.wake_armed ? "armed" : "disarmed",
             a.wake_active ? (a.wake_phrase ? a.wake_phrase : "?")
                           : "inactive: no model");
#else
    (void)cb;
    (void)user;
    (void)mic_cb;
    (void)mic_user;
#endif
}

int ubo_audio_init(i2c_master_bus_handle_t i2c) {
    ESP_LOGI(TAG, "audio init; free heap before: %lu",
             (unsigned long)esp_get_free_heap_size());

    if (i2s_setup() != ESP_OK) {
        ESP_LOGE(TAG, "I2S setup failed");
        return -1;
    }

    /* One I2S data interface, shared by whichever codec chips the board has.
     * Do NOT split this into separate tx-only/rx-only interfaces: the shared
     * one is what lets esp_codec_dev reconfigure the TX clock when only the RX
     * side is opened (and on the S3, defer an RX disable that would otherwise
     * stop TX too). */
    audio_codec_i2s_cfg_t i2s_cfg = {
        .port = I2S_NUM_0,
        .rx_handle = a.rx,
        .tx_handle = a.tx,
    };
    const audio_codec_data_if_t *data = audio_codec_new_i2s_data(&i2s_cfg);
    if (!data) {
        ESP_LOGE(TAG, "codec data interface alloc failed");
        return -1;
    }

    board_codecs_t codecs = {0};
    if (board_audio_codecs_init(i2c, data, &codecs) != 0) {
        ESP_LOGE(TAG, "board codec init failed");
        return -1;
    }
    a.out_dev = codecs.out;
    a.in_dev = codecs.in;
    a.mic_gain_db = codecs.mic_gain_db;

    a.lock = xSemaphoreCreateMutex();
#ifdef CONFIG_SPIRAM
    /* PSRAM: see PLAY_RING_BYTES. Never DMA'd, only memcpy'd in 1KB blocks. */
    a.play_ring =
        xStreamBufferCreateWithCaps(PLAY_RING_BYTES, 1, MALLOC_CAP_SPIRAM);
#else
    a.play_ring = xStreamBufferCreate(PLAY_RING_BYTES, 1);
#endif
    if (!a.lock || !a.play_ring) {
        ESP_LOGE(TAG, "audio buffer/lock alloc failed");
        return -1;
    }
#ifdef CONFIG_UBO_AFE_ENABLE
    /* Non-fatal: capture falls back to the raw single channel if this fails. */
    afe_setup();
#endif

    /* Enable the speaker amplifier (board-specific: IO-expander pin or GPIO). */
    board_speaker_amp_enable(true);
#ifdef CONFIG_UBO_MIC_SESSION_RECORDER
    a.rec_cap = 640 * 1024; /* ~20 s at 16 kHz mono, PSRAM */
    a.rec_buf = heap_caps_malloc(a.rec_cap, MALLOC_CAP_SPIRAM);
    if (!a.rec_buf) {
        a.rec_cap = 0;
    }
#endif
    /* Pinned to core 0, not left unpinned. play_task is priority 5, below both
     * `ubo_feed` (7) and `ubo_mic` (6) — and with a wake word those two sit on
     * core 1 running continuously, WakeNet inference included. Scheduled onto
     * core 1 this task would be the lowest-priority runnable thing there, which
     * is exactly what makes its 300ms codec-handover deadline miss. Core 0
     * carries WiFi/lwIP but nothing that starves a priority-5 task the way a
     * saturated core 1 does. */
    if (xTaskCreatePinnedToCore(play_task, "ubo_play", 4096, NULL, 5, NULL,
                                PLAY_TASK_CORE) != pdPASS) {
        ESP_LOGE(TAG, "play task creation failed");
        return -1;
    }

    ESP_LOGI(TAG, "audio ready (%s); free heap after: %lu", BOARD_NAME,
             (unsigned long)esp_get_free_heap_size());
    return 0;
}
