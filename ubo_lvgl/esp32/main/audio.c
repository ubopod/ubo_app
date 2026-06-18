#include "audio.h"

#include <string.h>

#include "board.h"
#include "driver/i2s_std.h"
#include "esp_codec_dev.h"
#include "esp_codec_dev_defaults.h"
#include "es8311_codec.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/stream_buffer.h"
#include "freertos/task.h"

static const char *TAG = "ubo_audio";

/* ── Waveshare ESP32-C6-Touch-AMOLED-1.8 audio pin map ── */
#define I2S_MCLK_GPIO 19
#define I2S_BCLK_GPIO 20
#define I2S_WS_GPIO 22
#define I2S_DOUT_GPIO 23 /* I2S -> codec DAC -> speaker */
#define I2S_DIN_GPIO 21  /* codec ADC (mic) -> I2S */
/* The speaker power amplifier enable is NOT an ESP32 GPIO on this board: it sits
 * on TCA9554 IO-expander pin 7 (BSP_POWER_AMP_IO), driven via
 * board_speaker_amp_enable(). The ES8311 codec's own pa_pin stays unset (-1). */

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

#define PLAY_RING_BYTES 16384 /* ~0.5 s @ 16 kHz/16-bit/mono; smooths HTTP jitter */
#define PLAY_DRAIN_CHUNK 1024
#define PLAY_IDLE_CLOSE_US 200000 /* close output (PA off) 200 ms after drain */

static struct {
    esp_codec_dev_handle_t dev;
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
    int r = esp_codec_dev_open(a.dev, &fs);
    if (r != 0) {
        ESP_LOGE(TAG, "codec open(out) failed: %d", r);
        return r;
    }
    int v = (int)(vol * 100.0f);
    esp_codec_dev_set_out_vol(a.dev, v < 0 ? 0 : (v > 100 ? 100 : v));
    a.out_open = true;
    a.out_rate = rate;
    a.out_ch = ch;
    a.out_width = width;
    return 0;
}

static void close_out(void) {
    if (a.out_open) {
        esp_codec_dev_close(a.dev); /* also drops PA via the codec gpio_if */
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
                esp_codec_dev_write(a.dev, buf, (int)n);
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
    if (!a.dev || !pcm || len == 0 || a.mic_active) {
        return;
    }
    a.want_rate = rate;
    a.want_ch = channels;
    a.want_width = width;
    a.want_vol = volume;
    xStreamBufferSend(a.play_ring, pcm, len, pdMS_TO_TICKS(100));
}

/* ── mic capture task: 16k mono frames -> accumulate a chunk -> callback ── */
static uint8_t s_mic_buf[MIC_BUF_BYTES];

static void mic_task(void *arg) {
    (void)arg;
    const size_t chunk_target = (size_t)CONFIG_UBO_MIC_CHUNK_MS * MIC_BYTES_PER_MS;
    size_t filled = 0;
    while (!a.mic_stop) {
        int r = esp_codec_dev_read(a.dev, s_mic_buf + filled, MIC_FRAME_BYTES);
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
    esp_codec_dev_close(a.dev);
    a.mic_active = false;
    xSemaphoreGive(a.lock);
    vTaskDelete(NULL);
}

void ubo_audio_mic_start(ubo_audio_mic_cb cb, void *user) {
    if (!a.dev) {
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
    if (esp_codec_dev_open(a.dev, &fs) != 0) {
        ESP_LOGE(TAG, "codec open(mic) failed");
        xSemaphoreGive(a.lock);
        return;
    }
    esp_codec_dev_set_in_gain(a.dev, 30.0f);
    a.mic_cb = cb;
    a.mic_user = user;
    a.mic_stop = false;
    a.mic_active = true;
    xSemaphoreGive(a.lock);
    xTaskCreate(mic_task, "ubo_mic", 4096, NULL, 6, NULL);
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

    audio_codec_i2c_cfg_t i2c_cfg = {
        .port = I2C_NUM_0,
        .addr = ES8311_CODEC_DEFAULT_ADDR,
        .bus_handle = i2c,
    };
    const audio_codec_ctrl_if_t *ctrl = audio_codec_new_i2c_ctrl(&i2c_cfg);
    const audio_codec_gpio_if_t *gpio = audio_codec_new_gpio();
    audio_codec_i2s_cfg_t i2s_cfg = {
        .port = I2S_NUM_0,
        .rx_handle = a.rx,
        .tx_handle = a.tx,
    };
    const audio_codec_data_if_t *data = audio_codec_new_i2s_data(&i2s_cfg);
    if (!ctrl || !gpio || !data) {
        ESP_LOGE(TAG, "codec interface alloc failed");
        return -1;
    }
    es8311_codec_cfg_t es_cfg = {
        .ctrl_if = ctrl,
        .gpio_if = gpio,
        .codec_mode = ESP_CODEC_DEV_WORK_MODE_BOTH,
        .pa_pin = -1, /* PA is on the IO-expander, not an ESP32 GPIO (see below) */
        .use_mclk = true,
    };
    const audio_codec_if_t *codec = es8311_codec_new(&es_cfg);
    if (!codec) {
        ESP_LOGE(TAG, "es8311_codec_new failed");
        return -1;
    }
    esp_codec_dev_cfg_t dev_cfg = {
        .dev_type = ESP_CODEC_DEV_TYPE_IN_OUT,
        .codec_if = codec,
        .data_if = data,
    };
    a.dev = esp_codec_dev_new(&dev_cfg);
    if (!a.dev) {
        ESP_LOGE(TAG, "esp_codec_dev_new failed");
        return -1;
    }

    a.lock = xSemaphoreCreateMutex();
    a.play_ring = xStreamBufferCreate(PLAY_RING_BYTES, 1);
    if (!a.lock || !a.play_ring) {
        ESP_LOGE(TAG, "audio buffer/lock alloc failed");
        return -1;
    }
    /* Enable the speaker amplifier (TCA9554 IO-expander pin 7). */
    board_speaker_amp_enable(true);
    xTaskCreate(play_task, "ubo_play", 4096, NULL, 5, NULL);

    ESP_LOGI(TAG, "audio ready (ES8311); free heap after: %lu",
             (unsigned long)esp_get_free_heap_size());
    return 0;
}
