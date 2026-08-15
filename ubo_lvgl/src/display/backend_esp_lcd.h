/**
 * @file backend_esp_lcd.h
 * ESP32 display backend over esp_lcd. Only built when UBO_WITH_ESP_LCD is
 * defined (the ESP-IDF firmware component).
 *
 * The firmware's board.c owns the board-specific hardware bring-up (I2C, reset,
 * SPI/QSPI bus, panel + panel-IO) and then hands the resulting esp_lcd handles
 * here via ubo_backend_esp_lcd_configure() BEFORE calling
 * ubo_lvgl_init(UBO_BACKEND_ESP_LCD); the backend wraps them in an lv_display
 * with DMA partial buffers. This keeps the generic renderer free of
 * board-specific driver components.
 *
 * The panel-family differences (flush-window alignment, RGB565 byte order,
 * draw-buffer sizing and placement) are data, not code — see the config struct.
 * Covers the SH8601 368x448 QSPI AMOLED and the ILI9341 320x240 SPI LCD.
 */
#ifndef UBO_BACKEND_ESP_LCD_H
#define UBO_BACKEND_ESP_LCD_H

#include <stdbool.h>
#include <stdint.h>

#include "esp_lcd_types.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    esp_lcd_panel_handle_t panel;
    esp_lcd_panel_io_handle_t io;
    /* Flush-window alignment in px on both axes. The SH8601 AMOLED requires 2;
     * 1 means unconstrained and skips the LV_EVENT_INVALIDATE_AREA rounder. */
    uint8_t align_px;
    /* Byte-swap RGB565 before draw_bitmap. True for esp_lcd SPI panels, which
     * ship bytes MSB-first while LVGL stores RGB565 little-endian. */
    bool swap_rgb565;
    /* Partial draw buffer height = panel height / this, double-buffered. */
    uint8_t buf_divisor;
    /* heap_caps flags for the two draw buffers. Must be DMA-capable — do NOT
     * put these in PSRAM: esp_lcd's SPI DMA wants cache-line-aligned memory
     * with an explicit writeback, and getting it wrong shows up as tearing. */
    uint32_t buf_caps;
} ubo_backend_esp_lcd_cfg;

/* Supply the panel handles + panel-family parameters. Call from board.c before
 * ubo_lvgl_init(). The struct is copied; the caller need not keep it alive. */
void ubo_backend_esp_lcd_configure(const ubo_backend_esp_lcd_cfg *cfg);

#ifdef __cplusplus
}
#endif
#endif /* UBO_BACKEND_ESP_LCD_H */
