/**
 * @file lv_conf.h
 * Minimal LVGL configuration for the Ubo renderer.
 *
 * Only values that differ from LVGL's built-in defaults (lv_conf_internal.h)
 * are set here. Target panel: ST7789 240x240, RGB565.
 */

#ifndef LV_CONF_H
#define LV_CONF_H

#include <stdint.h>

/* RGB565 to match the ST7789 panel. */
#define LV_COLOR_DEPTH 16

/* Use the C standard library for malloc/string/sprintf so we are not bound by a
 * fixed-size builtin heap (the desktop sim renders fonts + multiple screens). */
#define LV_USE_STDLIB_MALLOC  LV_STDLIB_CLIB
#define LV_USE_STDLIB_STRING  LV_STDLIB_CLIB
#define LV_USE_STDLIB_SPRINTF LV_STDLIB_CLIB

/* We manage threading ourselves with a pthread mutex around LVGL access, so
 * LVGL's own OS abstraction stays disabled. */
#define LV_USE_OS LV_OS_NONE

/* Logging to stdout, warnings and above. */
#define LV_USE_LOG      1
#define LV_LOG_LEVEL    LV_LOG_LEVEL_WARN
#define LV_LOG_PRINTF   1

/* Desktop simulator display backend. The Pi build drives ST7789 directly via a
 * hand-written flush_cb and does not enable SDL. */
#ifdef UBO_WITH_SDL
    #define LV_USE_SDL           1
    /* The SDL2 include dir (from CMake) points into .../include/SDL2, so the
     * header is reached as <SDL.h> rather than <SDL2/SDL.h>. */
    #define LV_SDL_INCLUDE_PATH  <SDL.h>
    #define LV_SDL_RENDER_MODE   LV_DISPLAY_RENDER_MODE_DIRECT
    #define LV_SDL_BUF_COUNT     1
    #define LV_SDL_ACCELERATED   1
    /* Close the window => exit the process (fine for the dev sim/bridge). */
    #define LV_SDL_DIRECT_EXIT   1
#endif

/* Fonts: Montserrat sizes used across the views + default. */
#define LV_FONT_MONTSERRAT_12 1
#define LV_FONT_MONTSERRAT_14 1
#define LV_FONT_MONTSERRAT_16 1
#define LV_FONT_MONTSERRAT_18 1
#define LV_FONT_MONTSERRAT_20 1
#define LV_FONT_MONTSERRAT_24 1
#define LV_FONT_MONTSERRAT_28 1
/* Larger sizes for high-res panels (the responsive layout nearest-picks). */
#define LV_FONT_MONTSERRAT_32 1
#define LV_FONT_MONTSERRAT_40 1
#define LV_FONT_MONTSERRAT_48 1
#define LV_FONT_DEFAULT &lv_font_montserrat_16

/* Filesystem driver so the full Material-Design-Icon font can be loaded at
 * runtime from a .bin (keeps the library small). Drive letter 'A'. */
#define LV_USE_FS_STDIO       1
#define LV_FS_STDIO_LETTER    'A'
#define LV_FS_STDIO_PATH      ""
#define LV_FS_STDIO_CACHE_SIZE 0

/* Widgets / extras used by the views. */
#define LV_USE_ARC      1
#define LV_USE_BAR      1
#define LV_USE_LABEL    1
#define LV_USE_SPINNER  1
#define LV_USE_IMAGE    1
#define LV_USE_ANIMIMG  1

/* QR codes for the generic RenderViewData 'qr_code'/'qr_code_carousel' kinds. */
#define LV_USE_QRCODE   1

#endif /* LV_CONF_H */
