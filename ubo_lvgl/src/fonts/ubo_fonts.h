/**
 * @file ubo_fonts.h
 * LVGL fonts generated from ArimoNerdFont (the same Nerd Font ubo_gui uses).
 * These cover the Material Design Icon glyphs in the Private Use Area.
 *
 * Regenerate with lv_font_conv (see scripts) when adding icon codepoints.
 */
#ifndef UBO_FONTS_H
#define UBO_FONTS_H

#include "lvgl.h"

extern const lv_font_t ubo_icon_18;
extern const lv_font_t ubo_icon_14;
/* Larger sizes for high-res panels (the responsive layout nearest-picks). */
extern const lv_font_t ubo_icon_24;
extern const lv_font_t ubo_icon_32;

/* Load the full-coverage icon fonts from `assets_dir` (may be NULL/empty to use
 * the compiled subset). Accessors return the loaded font or the fallback. */
void ubo_fonts_load(const char *assets_dir);
const lv_font_t *ubo_font_icon_18(void);
const lv_font_t *ubo_font_icon_14(void);

#endif /* UBO_FONTS_H */
