#include "board.h"

#include "display/backend_esp_lcd.h"
#include "driver/spi_master.h"
#include "es8311_codec.h"
#include "esp_check.h"
#include "esp_codec_dev_defaults.h"
#include "esp_heap_caps.h"
#include "esp_io_expander_tca9554.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_sh8601.h"
#include "esp_lcd_touch_ft5x06.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "ubo_board";

/* TCA9554 IO-expander handle (panel reset on pins 4,5; speaker amp on pin 7).
 * Created in board_display_init, reused by board_speaker_amp_enable. */
static esp_io_expander_handle_t s_io_expander;

/* ── Pin map (fixed for ESP32-C6-Touch-AMOLED-1.8; geometry in board_pins.h) ── */
#define LCD_HOST SPI2_HOST
#define PIN_LCD_CS 5
#define PIN_LCD_PCLK 0
#define PIN_LCD_D0 1
#define PIN_LCD_D1 2
#define PIN_LCD_D2 3
#define PIN_LCD_D3 4
#define PIN_TOUCH_SCL 7
#define PIN_TOUCH_SDA 8
#define PIN_TOUCH_INT 15
#define LCD_BITS_PER_PIXEL 16

/* SH8601 init sequence (Waveshare): sleep-out, TE on, brightness ctrl, window
 * 0..367 x 0..447, display on, full brightness. */
static const sh8601_lcd_init_cmd_t lcd_init_cmds[] = {
    {0x11, (uint8_t[]){0x00}, 0, 120},
    {0x44, (uint8_t[]){0x01, 0xD1}, 2, 0},
    {0x35, (uint8_t[]){0x00}, 1, 0},
    {0x53, (uint8_t[]){0x20}, 1, 10},
    {0x2A, (uint8_t[]){0x00, 0x00, 0x01, 0x6F}, 4, 0},
    {0x2B, (uint8_t[]){0x00, 0x00, 0x01, 0xBF}, 4, 0},
    {0x51, (uint8_t[]){0x00}, 1, 10},
    {0x29, (uint8_t[]){0x00}, 0, 10},
    {0x51, (uint8_t[]){0xFF}, 1, 0},
};

i2c_master_bus_handle_t board_i2c_init(void) {
    i2c_master_bus_handle_t bus = NULL;
    const i2c_master_bus_config_t cfg = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = PIN_TOUCH_SDA,
        .scl_io_num = PIN_TOUCH_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    ESP_ERROR_CHECK(i2c_new_master_bus(&cfg, &bus));
    ESP_LOGI(TAG, "I2C master bus ready (SDA=%d SCL=%d)", PIN_TOUCH_SDA, PIN_TOUCH_SCL);
    return bus;
}

esp_lcd_panel_handle_t board_display_init(i2c_master_bus_handle_t i2c) {
    /* 1. Pulse the panel reset lines through the TCA9554 IO-expander (pins 4,5). */
    esp_io_expander_handle_t io_expander = NULL;
    ESP_ERROR_CHECK(esp_io_expander_new_i2c_tca9554(
        i2c, ESP_IO_EXPANDER_I2C_TCA9554_ADDRESS_000, &io_expander));
    s_io_expander = io_expander; /* reused by board_speaker_amp_enable */
    esp_io_expander_set_dir(io_expander,
                            IO_EXPANDER_PIN_NUM_4 | IO_EXPANDER_PIN_NUM_5,
                            IO_EXPANDER_OUTPUT);
    esp_io_expander_set_level(io_expander,
                              IO_EXPANDER_PIN_NUM_4 | IO_EXPANDER_PIN_NUM_5, 0);
    vTaskDelay(pdMS_TO_TICKS(200));
    esp_io_expander_set_level(io_expander,
                              IO_EXPANDER_PIN_NUM_4 | IO_EXPANDER_PIN_NUM_5, 1);
    vTaskDelay(pdMS_TO_TICKS(200));

    /* 2. QSPI bus. */
    const spi_bus_config_t buscfg = SH8601_PANEL_BUS_QSPI_CONFIG(
        PIN_LCD_PCLK, PIN_LCD_D0, PIN_LCD_D1, PIN_LCD_D2, PIN_LCD_D3,
        BOARD_LCD_H_RES * BOARD_LCD_V_RES * LCD_BITS_PER_PIXEL / 8);
    ESP_ERROR_CHECK(spi_bus_initialize(LCD_HOST, &buscfg, SPI_DMA_CH_AUTO));

    /* 3. Panel IO + SH8601 panel driver. */
    esp_lcd_panel_io_handle_t io_handle = NULL;
    const esp_lcd_panel_io_spi_config_t io_config =
        SH8601_PANEL_IO_QSPI_CONFIG(PIN_LCD_CS, NULL, NULL);
    sh8601_vendor_config_t vendor_config = {
        .init_cmds = lcd_init_cmds,
        .init_cmds_size = sizeof(lcd_init_cmds) / sizeof(lcd_init_cmds[0]),
        .flags = {.use_qspi_interface = 1},
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)LCD_HOST,
                                             &io_config, &io_handle));

    esp_lcd_panel_handle_t panel = NULL;
    const esp_lcd_panel_dev_config_t panel_config = {
        .reset_gpio_num = -1, /* reset handled via the IO-expander above */
        .rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB,
        .bits_per_pixel = LCD_BITS_PER_PIXEL,
        .vendor_config = &vendor_config,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_sh8601(io_handle, &panel_config, &panel));
    ESP_ERROR_CHECK(esp_lcd_panel_reset(panel));
    ESP_ERROR_CHECK(esp_lcd_panel_init(panel));
    ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(panel, true));
    ESP_LOGI(TAG, "SH8601 panel ready (%dx%d)", BOARD_LCD_H_RES, BOARD_LCD_V_RES);

    /* Hand the panel to the renderer's esp_lcd backend. The AMOLED needs
     * 2px-aligned flush windows and byte-swapped RGB565; the C6 has no PSRAM,
     * so the two partial draw buffers come out of DMA-capable SRAM. */
    const ubo_backend_esp_lcd_cfg backend_cfg = {
        .panel = panel,
        .io = io_handle,
        .align_px = BOARD_LCD_ALIGN_PX,
        .swap_rgb565 = true,
        .buf_divisor = BOARD_LCD_BUF_DIVISOR,
        .buf_caps = MALLOC_CAP_DMA,
    };
    ubo_backend_esp_lcd_configure(&backend_cfg);
    return panel;
}

void board_speaker_amp_enable(bool on) {
    /* Speaker power amplifier enable = TCA9554 IO-expander pin 7
     * (BSP_POWER_AMP_IO). Not an ESP32 GPIO; driven via the shared expander. */
    if (!s_io_expander) {
        return;
    }
    esp_io_expander_set_dir(s_io_expander, IO_EXPANDER_PIN_NUM_7,
                            IO_EXPANDER_OUTPUT);
    esp_io_expander_set_level(s_io_expander, IO_EXPANDER_PIN_NUM_7, on ? 1 : 0);
}

esp_lcd_touch_handle_t board_touch_init(i2c_master_bus_handle_t i2c) {
    esp_lcd_panel_io_handle_t tp_io = NULL;
    const esp_lcd_panel_io_i2c_config_t tp_io_cfg =
        ESP_LCD_TOUCH_IO_I2C_FT5x06_CONFIG();
    ESP_ERROR_CHECK(esp_lcd_new_panel_io_i2c(i2c, &tp_io_cfg, &tp_io));

    const esp_lcd_touch_config_t tp_cfg = {
        .x_max = BOARD_LCD_H_RES,
        .y_max = BOARD_LCD_V_RES,
        .rst_gpio_num = -1,
        .int_gpio_num = PIN_TOUCH_INT,
        .levels = {.reset = 0, .interrupt = 0},
        .flags = {.swap_xy = BOARD_TOUCH_SWAP_XY,
                  .mirror_x = BOARD_TOUCH_MIRROR_X,
                  .mirror_y = BOARD_TOUCH_MIRROR_Y},
    };
    esp_lcd_touch_handle_t tp = NULL;
    ESP_ERROR_CHECK(esp_lcd_touch_new_i2c_ft5x06(tp_io, &tp_cfg, &tp));
    ESP_LOGI(TAG, "FT3168 touch ready");
    return tp;
}

int board_audio_codecs_init(i2c_master_bus_handle_t i2c,
                            const audio_codec_data_if_t *data_if,
                            board_codecs_t *out) {
    /* One ES8311 does both directions on this board, so `in` and `out` are the
     * same IN_OUT handle — audio.c's split call sites then behave exactly as
     * they did when it held a single handle. */
    audio_codec_i2c_cfg_t i2c_cfg = {
        .port = I2C_NUM_0,
        .addr = ES8311_CODEC_DEFAULT_ADDR,
        .bus_handle = i2c,
    };
    const audio_codec_ctrl_if_t *ctrl = audio_codec_new_i2c_ctrl(&i2c_cfg);
    const audio_codec_gpio_if_t *gpio = audio_codec_new_gpio();
    if (!ctrl || !gpio) {
        ESP_LOGE(TAG, "codec ctrl/gpio interface failed");
        return -1;
    }

    es8311_codec_cfg_t es_cfg = {
        .ctrl_if = ctrl,
        .gpio_if = gpio,
        .codec_mode = ESP_CODEC_DEV_WORK_MODE_BOTH,
        /* The speaker amp is on TCA9554 pin 7, not an ESP32 GPIO, so the codec
         * driver must not try to drive it: board_speaker_amp_enable() does. */
        .pa_pin = -1,
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
        .data_if = data_if,
    };
    esp_codec_dev_handle_t dev = esp_codec_dev_new(&dev_cfg);
    if (!dev) {
        ESP_LOGE(TAG, "esp_codec_dev_new failed");
        return -1;
    }

    out->out = dev;
    out->in = dev;
    out->mic_gain_db = BOARD_MIC_GAIN_DB;
    return 0;
}
