/**
 * @file fonts_runtime.c
 * Load the full Material-Design-Icon font from a .bin at runtime, falling back
 * to the small compiled-in subset (ubo_icon_*) when the assets dir is unset or
 * the file is missing.
 */
#include "fonts/ubo_fonts.h"

#include <stdio.h>

#include "views/ubo_views.h"

static const lv_font_t *s_icon_18;
static const lv_font_t *s_icon_14;

static lv_font_t *load_bin(const char *dir, const char *file)
{
    if (!dir || !dir[0]) {
        return NULL;
    }
    char path[1024];
    snprintf(path, sizeof(path), "A:%s/%s", dir, file);
    lv_font_t *f = lv_binfont_create(path);
    if (!f) {
        LV_LOG_WARN("could not load font %s", path);
    }
    return f;
}

/* Load the Nerd Font icon .bin (same font ubo_gui registers as DEFAULT_FONT),
 * which covers all icon ranges the core emits. Falls back to the small compiled
 * subset only if the .bin is unavailable. */
static const lv_font_t *load_icons(const char *dir, const char *file,
                                   const lv_font_t *compiled)
{
    lv_font_t *icon = load_bin(dir, file);
    return icon ? icon : compiled;
}

void ubo_fonts_load(const char *assets_dir)
{
    s_icon_18 = load_icons(assets_dir, "ubo_icons_18.bin", &ubo_icon_18);
    s_icon_14 = load_icons(assets_dir, "ubo_icons_14.bin", &ubo_icon_14);
}

const lv_font_t *ubo_font_icon_18(void)
{
    return s_icon_18 ? s_icon_18 : &ubo_icon_18;
}

const lv_font_t *ubo_font_icon_14(void)
{
    return s_icon_14 ? s_icon_14 : &ubo_icon_14;
}
