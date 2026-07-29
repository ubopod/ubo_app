#include "board.h"

#include "display/backend_esp_lcd.h"
#include "driver/gpio.h"
#include "driver/ledc.h"
#include "driver/spi_master.h"
#include "es7210_adc.h"
#include "es8311_codec.h"
#include "esp_check.h"
#include "esp_codec_dev_defaults.h"
#include "esp_heap_caps.h"
#include "esp_lcd_ili9341.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_touch_gt911.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "ubo_board";

/* ── Pin map (fixed for ESP32-S3-BOX-3; geometry in board_pins.h) ── */
#define LCD_HOST SPI3_HOST
#define PIN_LCD_PCLK 7
#define PIN_LCD_DATA0 6
#define PIN_LCD_CS 5
#define PIN_LCD_DC 4
#define PIN_LCD_RST 48 /* active HIGH, and shared with the touch controller */
#define PIN_LCD_BL 47
#define PIN_I2C_SDA 8
#define PIN_I2C_SCL 18
#define PIN_TOUCH_INT 3
#define PIN_POWER_AMP 46

#define LCD_BITS_PER_PIXEL 16
#define LCD_PIXEL_CLOCK_HZ (40 * 1000 * 1000)
#define LCD_CMD_BITS 8
#define LCD_PARAM_BITS 8

/* Backlight PWM. */
#define BL_LEDC_TIMER LEDC_TIMER_1
#define BL_LEDC_MODE LEDC_LOW_SPEED_MODE
#define BL_LEDC_CHANNEL LEDC_CHANNEL_1
#define BL_LEDC_DUTY_RES LEDC_TIMER_10_BIT
#define BL_LEDC_FREQ_HZ 5000

/* I2C addresses probed at bring-up. */
#define ADDR_TT21100 0x24 /* present only on the older ESP-BOX / BOX-3B */
#define ADDR_GT911_PRIMARY 0x5D
#define ADDR_GT911_ALT 0x14

/* Vendor init sequence for the BOX-3 panel, from espressif/esp-bsp
 * `bsp/esp-box-3`. Note 0x36 (MADCTL) = 0x08: BGR order, MV=0. The die is
 * natively landscape, so 320 columns work without swapping axes — the
 * esp_lcd_panel_mirror(true, true) below is the only orientation fix needed. */
static const ili9341_lcd_init_cmd_t lcd_init_cmds[] = {
    {0xC8, (uint8_t[]){0xFF, 0x93, 0x42}, 3, 0},
    {0xC0, (uint8_t[]){0x0E, 0x0E}, 2, 0},
    {0xC5, (uint8_t[]){0xD0}, 1, 0},
    {0xC1, (uint8_t[]){0x02}, 1, 0},
    {0xB4, (uint8_t[]){0x02}, 1, 0},
    {0xE0,
     (uint8_t[]){0x00, 0x03, 0x08, 0x06, 0x13, 0x09, 0x39, 0x39, 0x48, 0x02,
                 0x0a, 0x08, 0x17, 0x17, 0x0F},
     15, 0},
    {0xE1,
     (uint8_t[]){0x00, 0x28, 0x29, 0x01, 0x0d, 0x03, 0x3f, 0x33, 0x52, 0x04,
                 0x0f, 0x0e, 0x37, 0x38, 0x0F},
     15, 0},
    {0xB1, (uint8_t[]){0x00, 0x1B}, 2, 0},
    {0x36, (uint8_t[]){0x08}, 1, 0},
    {0x3A, (uint8_t[]){0x55}, 1, 0},
    {0xB7, (uint8_t[]){0x06}, 1, 0},
    {0x11, (uint8_t[]){0}, 0x80, 0},
    {0x29, (uint8_t[]){0}, 0x80, 0},
    {0, (uint8_t[]){0}, 0xff, 0},
};

i2c_master_bus_handle_t board_i2c_init(void) {
    i2c_master_bus_handle_t bus = NULL;
    const i2c_master_bus_config_t cfg = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = PIN_I2C_SDA,
        .scl_io_num = PIN_I2C_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    ESP_ERROR_CHECK(i2c_new_master_bus(&cfg, &bus));
    ESP_LOGI(TAG, "I2C master bus ready (SDA=%d SCL=%d)", PIN_I2C_SDA,
             PIN_I2C_SCL);
    return bus;
}

/* Backlight on GPIO47 via LEDC PWM. percent is clamped to 0..100. Local to this
 * board: the C6 AMOLED has no separate backlight rail (brightness is an SH8601
 * register), so there is nothing to put behind a shared board.h entry point
 * until display blanking actually needs one. */
static void board_backlight_set(int percent) {
    static bool configured;
    if (!configured) {
        const ledc_timer_config_t timer = {
            .speed_mode = BL_LEDC_MODE,
            .duty_resolution = BL_LEDC_DUTY_RES,
            .timer_num = BL_LEDC_TIMER,
            .freq_hz = BL_LEDC_FREQ_HZ,
            .clk_cfg = LEDC_AUTO_CLK,
        };
        ESP_ERROR_CHECK(ledc_timer_config(&timer));
        const ledc_channel_config_t ch = {
            .gpio_num = PIN_LCD_BL,
            .speed_mode = BL_LEDC_MODE,
            .channel = BL_LEDC_CHANNEL,
            .timer_sel = BL_LEDC_TIMER,
            .duty = 0,
            .hpoint = 0,
        };
        ESP_ERROR_CHECK(ledc_channel_config(&ch));
        configured = true;
    }
    const int pct = percent < 0 ? 0 : (percent > 100 ? 100 : percent);
    const uint32_t max_duty = (1U << BL_LEDC_DUTY_RES) - 1;
    ESP_ERROR_CHECK(
        ledc_set_duty(BL_LEDC_MODE, BL_LEDC_CHANNEL, max_duty * pct / 100));
    ESP_ERROR_CHECK(ledc_update_duty(BL_LEDC_MODE, BL_LEDC_CHANNEL));
}

esp_lcd_panel_handle_t board_display_init(i2c_master_bus_handle_t i2c) {
    /* The older ESP-BOX / BOX-3B pairs a TT21100 touch controller with an
     * ST7789 panel; this firmware only carries the BOX-3's driver. Probing is
     * cheap and turns "the screen is dead" into an actionable log line. */
    if (i2c_master_probe(i2c, ADDR_TT21100, 50) == ESP_OK) {
        ESP_LOGE(TAG,
                 "TT21100 found at 0x%02X: this is an ESP-BOX / BOX-3B "
                 "(ST7789 + TT21100), not an ESP32-S3-BOX-3. The display will "
                 "not work with this build.",
                 ADDR_TT21100);
    }

    /* 1. SPI bus. max_transfer_sz only has to cover one LVGL draw buffer, not a
     * whole frame — oversizing it just burns DMA descriptors. */
    const spi_bus_config_t buscfg = {
        .sclk_io_num = PIN_LCD_PCLK,
        .mosi_io_num = PIN_LCD_DATA0,
        .miso_io_num = GPIO_NUM_NC,
        .quadwp_io_num = GPIO_NUM_NC,
        .quadhd_io_num = GPIO_NUM_NC,
        .max_transfer_sz = BOARD_LCD_H_RES *
                           (BOARD_LCD_V_RES / BOARD_LCD_BUF_DIVISOR) *
                           sizeof(uint16_t),
    };
    ESP_ERROR_CHECK(spi_bus_initialize(LCD_HOST, &buscfg, SPI_DMA_CH_AUTO));

    /* 2. Panel IO + ILI9341-family panel driver. */
    esp_lcd_panel_io_handle_t io_handle = NULL;
    const esp_lcd_panel_io_spi_config_t io_config = {
        .dc_gpio_num = PIN_LCD_DC,
        .cs_gpio_num = PIN_LCD_CS,
        .pclk_hz = LCD_PIXEL_CLOCK_HZ,
        .lcd_cmd_bits = LCD_CMD_BITS,
        .lcd_param_bits = LCD_PARAM_BITS,
        .spi_mode = 0,
        .trans_queue_depth = 10,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)LCD_HOST,
                                             &io_config, &io_handle));

    const ili9341_vendor_config_t vendor_config = {
        .init_cmds = lcd_init_cmds,
        .init_cmds_size = sizeof(lcd_init_cmds) / sizeof(lcd_init_cmds[0]),
    };
    esp_lcd_panel_handle_t panel = NULL;
    const esp_lcd_panel_dev_config_t panel_config = {
        /* Reset is active HIGH here, and the line is shared with the touch
         * controller — which is why board_touch_init passes rst_gpio_num = -1
         * rather than pulsing it a second time. */
        .reset_gpio_num = PIN_LCD_RST,
        .flags.reset_active_high = 1,
        .rgb_ele_order = LCD_RGB_ELEMENT_ORDER_BGR,
        .bits_per_pixel = LCD_BITS_PER_PIXEL,
        .vendor_config = (void *)&vendor_config,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_ili9341(io_handle, &panel_config, &panel));
    ESP_ERROR_CHECK(esp_lcd_panel_reset(panel));
    ESP_ERROR_CHECK(esp_lcd_panel_init(panel));
    ESP_ERROR_CHECK(esp_lcd_panel_mirror(panel, true, true));
    ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(panel, true));
    ESP_LOGI(TAG, "ILI9341 panel ready (%dx%d)", BOARD_LCD_H_RES,
             BOARD_LCD_V_RES);

    /* 3. Hand the panel to the renderer's esp_lcd backend. No alignment
     * constraint on this panel; the draw buffers stay in internal DMA SRAM. */
    const ubo_backend_esp_lcd_cfg backend_cfg = {
        .panel = panel,
        .io = io_handle,
        .align_px = BOARD_LCD_ALIGN_PX,
        .swap_rgb565 = true,
        .buf_divisor = BOARD_LCD_BUF_DIVISOR,
        .buf_caps = MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL,
    };
    ubo_backend_esp_lcd_configure(&backend_cfg);

    board_backlight_set(100);
    return panel;
}

esp_lcd_touch_handle_t board_touch_init(i2c_master_bus_handle_t i2c) {
    /* The GT911 latches its I2C address from the INT level at reset, so it
     * answers at either 0x5D or 0x14 depending on how the board came up. We
     * don't own the shared reset line, so probe instead of assuming. */
    esp_lcd_panel_io_i2c_config_t tp_io_cfg = ESP_LCD_TOUCH_IO_I2C_GT911_CONFIG();
    if (i2c_master_probe(i2c, ADDR_GT911_PRIMARY, 50) != ESP_OK) {
        tp_io_cfg.dev_addr = ADDR_GT911_ALT;
    }
    ESP_LOGI(TAG, "GT911 at 0x%02X", (unsigned)tp_io_cfg.dev_addr);

    esp_lcd_panel_io_handle_t tp_io = NULL;
    ESP_ERROR_CHECK(esp_lcd_new_panel_io_i2c(i2c, &tp_io_cfg, &tp_io));

    const esp_lcd_touch_config_t tp_cfg = {
        .x_max = BOARD_LCD_H_RES,
        .y_max = BOARD_LCD_V_RES,
        .rst_gpio_num = -1, /* shared with the LCD; already pulsed above */
        .int_gpio_num = PIN_TOUCH_INT,
        .levels = {.reset = 0, .interrupt = 0},
        .flags = {.swap_xy = BOARD_TOUCH_SWAP_XY,
                  .mirror_x = BOARD_TOUCH_MIRROR_X,
                  .mirror_y = BOARD_TOUCH_MIRROR_Y},
    };
    esp_lcd_touch_handle_t tp = NULL;
    ESP_ERROR_CHECK(esp_lcd_touch_new_i2c_gt911(tp_io, &tp_cfg, &tp));
    ESP_LOGI(TAG, "GT911 touch ready");
    return tp;
}

void board_speaker_amp_enable(bool on) {
    /* A plain GPIO on this board (the C6 AMOLED puts it on an IO-expander).
     * Kept out of the ES8311's own pa_pin so the amp is enabled once at init
     * and stays on, rather than following codec open/close — that matches the
     * other board and keeps audio.c's play state machine identical. */
    static bool configured;
    if (!configured) {
        const gpio_config_t pa = {
            .pin_bit_mask = 1ULL << PIN_POWER_AMP,
            .mode = GPIO_MODE_OUTPUT,
        };
        ESP_ERROR_CHECK(gpio_config(&pa));
        configured = true;
    }
    gpio_set_level(PIN_POWER_AMP, on ? 1 : 0);
}

int board_audio_codecs_init(i2c_master_bus_handle_t i2c,
                            const audio_codec_data_if_t *data_if,
                            board_codecs_t *out) {
    const audio_codec_gpio_if_t *gpio = audio_codec_new_gpio();
    if (!gpio) {
        ESP_LOGE(TAG, "codec gpio interface failed");
        return -1;
    }

    /* ── Speaker: ES8311, DAC only (the mics are a separate chip) ── */
    audio_codec_i2c_cfg_t dac_i2c = {
        .port = I2C_NUM_0,
        .addr = ES8311_CODEC_DEFAULT_ADDR,
        .bus_handle = i2c,
    };
    const audio_codec_ctrl_if_t *dac_ctrl = audio_codec_new_i2c_ctrl(&dac_i2c);
    if (!dac_ctrl) {
        ESP_LOGE(TAG, "ES8311 i2c ctrl failed");
        return -1;
    }
    es8311_codec_cfg_t dac_cfg = {
        .ctrl_if = dac_ctrl,
        .gpio_if = gpio,
        .codec_mode = ESP_CODEC_DEV_WORK_MODE_DAC,
        .pa_pin = -1, /* driven by board_speaker_amp_enable() instead */
        .use_mclk = true,
        .master_mode = false, /* the ESP32 is I2S master */
        .hw_gain = {.pa_voltage = 5.0f, .codec_dac_voltage = 3.3f},
    };
    const audio_codec_if_t *dac = es8311_codec_new(&dac_cfg);
    if (!dac) {
        ESP_LOGE(TAG, "es8311_codec_new failed");
        return -1;
    }

    /* ── Mics: ES7210 ADC. Selecting exactly two mics keeps it out of TDM mode
     * (the driver only switches at >= 3), so it shares the plain 2-slot 16-bit
     * I2S STD frame the ES8311 already uses — no separate slot config. ── */
    audio_codec_i2c_cfg_t adc_i2c = {
        .port = I2C_NUM_0,
        .addr = ES7210_CODEC_DEFAULT_ADDR,
        .bus_handle = i2c,
    };
    const audio_codec_ctrl_if_t *adc_ctrl = audio_codec_new_i2c_ctrl(&adc_i2c);
    if (!adc_ctrl) {
        ESP_LOGE(TAG, "ES7210 i2c ctrl failed");
        return -1;
    }
    es7210_codec_cfg_t adc_cfg = {
        .ctrl_if = adc_ctrl,
        .master_mode = false,
        .mic_selected = ES7210_SEL_MIC1 | ES7210_SEL_MIC2,
    };
    const audio_codec_if_t *adc = es7210_codec_new(&adc_cfg);
    if (!adc) {
        ESP_LOGE(TAG, "es7210_codec_new failed");
        return -1;
    }

    /* Both devices share the one I2S data interface — that is what lets
     * esp_codec_dev reconfigure the TX clock when only the RX side is opened,
     * and (on this SoC generation) defer an RX disable that would stop TX too. */
    esp_codec_dev_cfg_t out_cfg = {
        .dev_type = ESP_CODEC_DEV_TYPE_OUT,
        .codec_if = dac,
        .data_if = data_if,
    };
    esp_codec_dev_cfg_t in_cfg = {
        .dev_type = ESP_CODEC_DEV_TYPE_IN,
        .codec_if = adc,
        .data_if = data_if,
    };
    out->out = esp_codec_dev_new(&out_cfg);
    out->in = esp_codec_dev_new(&in_cfg);
    out->mic_gain_db = BOARD_MIC_GAIN_DB;
    if (!out->out || !out->in) {
        ESP_LOGE(TAG, "esp_codec_dev_new failed (out=%p in=%p)", out->out,
                 out->in);
        return -1;
    }
    ESP_LOGI(TAG, "codecs ready (ES8311 out + ES7210 in, 2 mics)");
    return 0;
}
