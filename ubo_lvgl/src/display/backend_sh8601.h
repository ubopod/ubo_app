/**
 * @file backend_sh8601.h
 * ESP32-C6 SH8601 AMOLED display backend (QSPI). Only built when
 * UBO_WITH_SH8601 is defined (the ESP-IDF firmware component).
 *
 * The firmware (board.c) owns the board-specific hardware bring-up (I2C,
 * TCA9554 reset, QSPI bus, SH8601 panel + panel-IO). It hands the resulting
 * esp_lcd handles to this backend via ubo_backend_sh8601_set_panel() BEFORE
 * calling ubo_lvgl_init(UBO_BACKEND_SH8601); the backend then wraps them in an
 * lv_display with DMA partial buffers. This keeps the generic renderer free of
 * board-specific driver components.
 */
#ifndef UBO_BACKEND_SH8601_H
#define UBO_BACKEND_SH8601_H

#include "esp_lcd_types.h"

#ifdef __cplusplus
extern "C" {
#endif

void ubo_backend_sh8601_set_panel(esp_lcd_panel_handle_t panel,
                                  esp_lcd_panel_io_handle_t io);

#ifdef __cplusplus
}
#endif
#endif /* UBO_BACKEND_SH8601_H */
