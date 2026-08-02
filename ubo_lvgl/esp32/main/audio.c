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
#define PLAY_IDLE_CLOSE_US 2000000 /* 2 s */


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
#else
#define AFE_ACTIVE 0
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
#endif
    i2s_chan_handle_t tx;
    i2s_chan_handle_t rx;
    SemaphoreHandle_t lock; /* serializes dev open/close + mode transitions */
    StreamBufferHandle_t play_ring;

    bool out_open;
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
    volatile bool mic_active;
    volatile bool mic_stop;
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
        if (a.mic_active) {
            /* Don't play during a talk session; discard any stale audio. */
            if (n > 0) {
                xStreamBufferReset(a.play_ring);
            }
            close_out();
            xSemaphoreGive(a.lock);
            continue;
        }
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
        }
        xSemaphoreGive(a.lock);
    }
}

void ubo_audio_play(const uint8_t *pcm, size_t len, int rate, int channels,
                    int width, float volume) {
    if (!a.out_dev || !pcm || len == 0) {
        return;
    }
    if (a.mic_active) {
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
    /* Deliberately ahead of clearing `mic_active`: the dump describes the
     * session that is ending, and capture must stay shut while it drains. The
     * cost is that playback is refused meanwhile -- acceptable only because
     * this is a debug build. */
    rec_dump();
#endif
    xSemaphoreTake(a.lock, portMAX_DELAY);
    esp_codec_dev_close(a.in_dev);
    a.mic_active = false;
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
    while (!a.mic_stop) {
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
        { /* TEMP diagnostic: is the codec actually giving us 2ch audio? */
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
    a.mic_stop = true; /* unblock the fetch task if we exited on error */
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
    while (!a.mic_stop) {
        afe_fetch_result_t *res =
            a.afe->fetch_with_delay(a.afe_data, pdMS_TO_TICKS(100));
        if (!res || res->ret_value != 0 || res->data_size <= 0) {
            continue;
        }
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
    /* Wait for the feed task to leave the codec before closing it. */
    xSemaphoreTake(a.afe_feed_idle, pdMS_TO_TICKS(500));
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
 * AFE_TYPE_SR because ubo-core does the recognition; we only want a cleaner
 * single channel out. Buffers go to PSRAM: internal RAM is the scarce resource
 * here and AFE's are large. Returns 0 on success; a failure is non-fatal, the
 * caller falls back to raw capture. */
static int afe_setup(void) {
    afe_config_t *cfg =
        afe_config_init(AFE_INPUT_FORMAT, NULL, AFE_TYPE_VC, AFE_MODE_HIGH_PERF);
    if (!cfg) {
        ESP_LOGE(TAG, "afe_config_init failed");
        return -1;
    }
    cfg->aec_init = false;      /* no reference channel wired; see Kconfig */
    cfg->wakenet_init = false;  /* phase 2 */
    /* VAD is enabled for CHANNEL SELECTION, not for turn detection — ubo-core
     * still owns that and we ignore vad_state entirely. With SE(BSS) running,
     * something has to pick which separated source is the speaker:
     * esp_afe_config.h says the output channel is chosen "by wakenet or vad",
     * and with both off the selection stuck on a suppressed source, which AGC
     * then amplified into full-scale noise. That was the entire "BSS outputs a
     * constant" symptom. */
    cfg->vad_init = true;
    cfg->vad_enable_channel_trigger = true;
    /* AGC is what stops close talking from clipping the way the fixed 30dB
     * analog gain does. WEBRTC mode rather than WAKENET, which derives its gain
     * from the wake-word model we do not load yet. Note afe_config_check()
     * prioritises SE(BSS) over NS for two-microphone input, so the pipeline is
     * BSS + AGC; that is expected, not a misconfiguration. */
    /* AGC ON. It was disabled earlier on the theory that it caused output
     * "pinned at a constant peak of 15402" — that turned out to be the SE(BSS)
     * channel, which fetch was selecting regardless of AGC, so the reasoning
     * was invalid. A recorded session measures peak -24 dBFS / rms -41.6 dBFS
     * with no clipping, and the ES7210 is already at its maximum 37.5 dB analog
     * gain, so the missing ~15-20 dB has to come from here. */
    cfg->agc_init = true;
    cfg->agc_mode = AFE_AGC_MODE_WEBRTC; /* WAKENET mode needs a model we do
                                          * not load until phase 2 */
    /* CRITICAL. Without this, AFE picks its output channel "by wakenet or vad"
     * (esp_afe_config.h) — and we deliberately run with both disabled, because
     * ubo-core owns turn detection and the wake word is phase 2. Nothing then
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
                  "fixed_out=%d out_playback=%d se=%d ns=%d",
             cfg->pcm_config.total_ch_num, cfg->pcm_config.mic_num,
             cfg->pcm_config.ref_num, cfg->pcm_config.sample_rate,
             (int)cfg->fixed_output_channel, (int)cfg->output_playback_channel,
             (int)cfg->se_init, (int)cfg->ns_init);

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
        xTaskCreatePinnedToCoreWithCaps(afe_fetch_task, "ubo_mic",
                                        AFE_TASK_STACK, NULL, 6, NULL, 0,
                                        MALLOC_CAP_SPIRAM) != pdPASS ||
        /* Feed goes on core 1, at a higher priority, DELIBERATELY away from
         * fetch. Both were on core 0 — which also carries WiFi and lwIP — so
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
    return 0;
}
#endif

void ubo_audio_mic_start(ubo_audio_mic_cb cb, void *user) {
    if (!a.in_dev) {
        return;
    }
    xSemaphoreTake(a.lock, portMAX_DELAY);
    if (a.mic_active) {
        xSemaphoreGive(a.lock);
        return;
    }
    close_out(); /* free the codec from any playback session first */
    /* AFE needs both microphone channels; the plain path asks for one and the
     * i2s data interface maps that to slot 0. */
    const uint8_t mic_channels = AFE_ACTIVE ? 2 : 1;
    esp_codec_dev_sample_info_t fs = {
        .bits_per_sample = 16,
        .channel = mic_channels,
        .sample_rate = MIC_RATE,
    };
    if (esp_codec_dev_open(a.in_dev, &fs) != 0) {
        ESP_LOGE(TAG, "codec open(mic) failed");
        xSemaphoreGive(a.lock);
        return;
    }
    /* Re-apply after open. NOTE: in 2-channel (AFE) mode the captured level
     * comes out ~36dB lower than the mono path at the same setting — raw peaks
     * of ~500 vs clipping at 32767 — which starves AFE's AGC and makes it
     * amplify the noise floor instead of speech. Logged so the actual applied
     * gain is visible rather than assumed. */
    ESP_LOGW(TAG, "mic open: internal free %u, DMA-capable free %u",
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_DMA));
    const int gr = esp_codec_dev_set_in_gain(a.in_dev, a.mic_gain_db);
    ESP_LOGW(TAG, "set_in_gain(%.1f dB) rc=%d ch=%u", (double)a.mic_gain_db, gr,
             (unsigned)mic_channels);
    a.mic_cb = cb;
    a.mic_user = user;
    a.mic_stop = false;
    a.mic_active = true;
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
        a.mic_active = false;
        esp_codec_dev_close(a.in_dev);
        xSemaphoreGive(a.lock);
    }
}

void ubo_audio_mic_stop(void) {
    a.mic_stop = true; /* mic_task tears down + clears mic_active */
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
    if (xTaskCreate(play_task, "ubo_play", 4096, NULL, 5, NULL) != pdPASS) {
        ESP_LOGE(TAG, "play task creation failed");
        return -1;
    }

    ESP_LOGI(TAG, "audio ready (%s); free heap after: %lu", BOARD_NAME,
             (unsigned long)esp_get_free_heap_size());
    return 0;
}
