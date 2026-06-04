#include "board.h"

#include "driver/spi_master.h"
#include "esp_check.h"
#include "esp_io_expander_tca9554.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_sh8601.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "ubo_board";

/* ── Pin map (fixed for ESP32-C6-Touch-AMOLED-1.8) ── */
#define LCD_HOST SPI2_HOST
#define PIN_LCD_CS 5
#define PIN_LCD_PCLK 0
#define PIN_LCD_D0 1
#define PIN_LCD_D1 2
#define PIN_LCD_D2 3
#define PIN_LCD_D3 4
#define PIN_TOUCH_SCL 7
#define PIN_TOUCH_SDA 8
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

esp_lcd_panel_handle_t board_display_init(i2c_master_bus_handle_t i2c,
                                          esp_lcd_panel_io_handle_t *out_io) {
    /* 1. Pulse the panel reset lines through the TCA9554 IO-expander (pins 4,5). */
    esp_io_expander_handle_t io_expander = NULL;
    ESP_ERROR_CHECK(esp_io_expander_new_i2c_tca9554(
        i2c, ESP_IO_EXPANDER_I2C_TCA9554_ADDRESS_000, &io_expander));
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
    if (out_io) {
        *out_io = io_handle;
    }
    return panel;
}
