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

/* Offscreen RGB565 framebuffer backend. Always available; used for headless
 * snapshot verification (UBO_BACKEND_BUFFER). */
lv_display_t *ubo_backend_buffer_create(int32_t width, int32_t height);
const uint8_t *ubo_backend_buffer_data(void); /* width*height*2 bytes, or NULL */
int32_t ubo_backend_buffer_width(void);
int32_t ubo_backend_buffer_height(void);

#endif /* UBO_DISPLAY_BACKEND_H */
