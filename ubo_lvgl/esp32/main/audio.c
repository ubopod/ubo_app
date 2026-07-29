#include "audio.h"

#include <string.h>

#include "board.h"
#include "driver/i2s_std.h"
#include "esp_codec_dev.h"
#include "esp_heap_caps.h"
#include "esp_codec_dev_defaults.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/stream_buffer.h"
#include "freertos/task.h"

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

static struct {
    /* Codec device handles, supplied by board_audio_codecs_init(). On boards
     * where one chip does both directions these alias the same IN_OUT handle;
     * on the ESP32-S3-BOX-3 they are distinct (ES8311 DAC + ES7210 mic ADC)
     * sharing one I2S data interface. */
    esp_codec_dev_handle_t out_dev;
    esp_codec_dev_handle_t in_dev;
    float mic_gain_db;
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

    volatile bool mic_active;
    volatile bool mic_stop;
    volatile bool flush; /* discard buffered playback (AudioStopPlaybackEvent) */
    ubo_audio_mic_cb mic_cb;
    void *mic_user;
} a;

/* ── I2S full-duplex std channel (left disabled; esp_codec_dev enables on open) ── */
static esp_err_t i2s_setup(void) {
    i2s_chan_config_t cc = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    cc.auto_clear = true; /* zero the TX DMA on underrun to avoid noise */
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
    if (!a.out_dev || !pcm || len == 0 || a.mic_active) {
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
            if (a.mic_cb) {
                a.mic_cb(a.mic_user, s_mic_buf, filled,
                         (float)(esp_timer_get_time() / 1000000.0));
            }
            filled = 0;
        }
    }
    xSemaphoreTake(a.lock, portMAX_DELAY);
    esp_codec_dev_close(a.in_dev);
    a.mic_active = false;
    xSemaphoreGive(a.lock);
    vTaskDelete(NULL);
}

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
    esp_codec_dev_sample_info_t fs = {
        .bits_per_sample = 16,
        .channel = 1,
        .sample_rate = MIC_RATE,
    };
    if (esp_codec_dev_open(a.in_dev, &fs) != 0) {
        ESP_LOGE(TAG, "codec open(mic) failed");
        xSemaphoreGive(a.lock);
        return;
    }
    esp_codec_dev_set_in_gain(a.in_dev, a.mic_gain_db);
    a.mic_cb = cb;
    a.mic_user = user;
    a.mic_stop = false;
    a.mic_active = true;
    xSemaphoreGive(a.lock);
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
    /* Enable the speaker amplifier (board-specific: IO-expander pin or GPIO). */
    board_speaker_amp_enable(true);
    if (xTaskCreate(play_task, "ubo_play", 4096, NULL, 5, NULL) != pdPASS) {
        ESP_LOGE(TAG, "play task creation failed");
        return -1;
    }

    ESP_LOGI(TAG, "audio ready (%s); free heap after: %lu", BOARD_NAME,
             (unsigned long)esp_get_free_heap_size());
    return 0;
}
