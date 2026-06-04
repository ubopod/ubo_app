/**
 * @file board.h
 * Hardware bring-up for the Waveshare ESP32-C6-Touch-AMOLED-1.8.
 *
 * Owns the platform peripherals (shared I2C master bus, SH8601 QSPI AMOLED
 * panel, FT3168 touch). The LVGL display backend (src/display/backend_sh8601.c)
 * wraps the panel handle returned here; the touch input driver wraps the touch
 * handle. Pin map is fixed for this board.
 */
#ifndef UBO_BOARD_H
#define UBO_BOARD_H

#include "driver/i2c_master.h"
#include "esp_lcd_types.h"

#ifdef __cplusplus
extern "C" {
#endif

#define BOARD_LCD_H_RES 368
#define BOARD_LCD_V_RES 448

/* Create the shared I2C master bus (touch + TCA9554 IO-expander live here). */
i2c_master_bus_handle_t board_i2c_init(void);

/* Reset (via TCA9554) and initialize the SH8601 QSPI panel. Returns the panel
 * handle, ready for esp_lcd_panel_draw_bitmap, and (if out_io != NULL) outputs
 * the panel-IO handle so the LVGL backend can register its DMA-done callback. */
esp_lcd_panel_handle_t board_display_init(i2c_master_bus_handle_t i2c,
                                          esp_lcd_panel_io_handle_t *out_io);

#ifdef __cplusplus
}
#endif
#endif /* UBO_BOARD_H */
