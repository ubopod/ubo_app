/**
 * @file backend.h
 * Display backend factory. Each backend returns a ready LVGL display.
 */
#ifndef UBO_DISPLAY_BACKEND_H
#define UBO_DISPLAY_BACKEND_H

#include "lvgl.h"

#ifdef UBO_WITH_SDL
lv_display_t *ubo_backend_sdl_create(int32_t width, int32_t height);
#endif

#ifdef UBO_WITH_ST7789
lv_display_t *ubo_backend_st7789_create(int32_t width, int32_t height);
void ubo_backend_st7789_set_backlight(bool on); /* GPIO26 */
#endif

#ifdef UBO_WITH_SH8601
/* ESP32-C6 SH8601 AMOLED (QSPI). The firmware initializes the panel hardware
 * and hands the handles to backend_sh8601 via ubo_backend_sh8601_set_panel()
 * (see backend_sh8601.h) before calling ubo_lvgl_init(). */
lv_display_t *ubo_backend_sh8601_create(int32_t width, int32_t height);
#endif

/* Offscreen RGB565 framebuffer backend. Always available; used for headless
 * snapshot verification (UBO_BACKEND_BUFFER). */
lv_display_t *ubo_backend_buffer_create(int32_t width, int32_t height);
const uint8_t *ubo_backend_buffer_data(void); /* width*height*2 bytes, or NULL */
int32_t ubo_backend_buffer_width(void);
int32_t ubo_backend_buffer_height(void);

#endif /* UBO_DISPLAY_BACKEND_H */
