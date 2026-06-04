/**
 * @file ubo_views.h
 * Internal interface for the view layer: persistent screen chrome (header /
 * content / footer), the status bar, and per-view builders. All functions run
 * under the ubo_lock() held by the public render entry points.
 */
#ifndef UBO_VIEWS_H
#define UBO_VIEWS_H

#include "lvgl.h"

#include "fonts/ubo_fonts.h"
#include "ubo_lvgl.h"

/* ---- Responsive layout ----
 * All geometry + font sizes derive from the panel size by a single uniform
 * scale relative to the 240x240 reference design (scale = height / 240). The
 * reference values mirror ubo_gui; at 240x240 scale==1 reproduces them exactly
 * (desktop/Pi unchanged), and a larger panel scales everything together so the
 * header/footer/menu band and the fonts/icons stay in proportion.
 *
 * Computed once in ubo_layout_init(w,h) (ubo_lvgl.c) and read via ubo_layout().
 * The constant names below are kept as accessor macros so the view code is
 * unchanged. */
#define UBO_REF_DIM      240 /* reference panel (square) */
#define UBO_REF_HEADER   34  /* ubo_gui app.kv header */
#define UBO_REF_FOOTER   36  /* ubo_gui app.kv footer */
#define UBO_REF_ITEM_H   52  /* ubo_gui MENU_ITEM_HEIGHT */
#define UBO_REF_ITEM_GAP 7   /* ubo_gui MENU_ITEM_GAP */
#define UBO_REF_SHORT_W  46  /* ubo_gui SHORT_WIDTH */

typedef struct {
    int w, h;
    int header_h, footer_h, content_h;
    int item_h, item_gap, item_radius, short_w;
    /* Fonts chosen by nearest available size to (reference * scale). */
    const lv_font_t *f_xs;     /* ref montserrat 12 */
    const lv_font_t *f_sm;     /* ref montserrat 14 */
    const lv_font_t *f_md;     /* ref montserrat 16 */
    const lv_font_t *f_lg;     /* ref montserrat 18 (menu item label) */
    const lv_font_t *f_xl;     /* ref montserrat 20 (heading) */
    const lv_font_t *f_xxl;    /* ref montserrat 28 (overlay) */
    const lv_font_t *f_icon;   /* ref icon 18 */
    const lv_font_t *f_icon_sm; /* ref icon 14 */
} ubo_layout_t;

/* Compute the layout for a panel size; call once at init before any render. */
void ubo_layout_init(int w, int h);
/* The current layout (valid after ubo_layout_init). */
const ubo_layout_t *ubo_layout(void);

/* Scale a reference (240-panel) pixel value to the current panel. Lets per-view
 * dimensions (gauges, bars) stay responsive without bespoke layout fields. */
#define UBO_SCALE(ref) (((ref) * ubo_layout()->h + 120) / 240)

/* Geometry accessor macros (unchanged names; now responsive). */
#define UBO_W           (ubo_layout()->w)
#define UBO_H           (ubo_layout()->h)
#define UBO_HEADER_H    (ubo_layout()->header_h)
#define UBO_FOOTER_H    (ubo_layout()->footer_h)
#define UBO_CONTENT_H   (ubo_layout()->content_h)
#define UBO_ITEM_H      (ubo_layout()->item_h)
#define UBO_ITEM_GAP    (ubo_layout()->item_gap)
#define UBO_SHORT_W     (ubo_layout()->short_w)
#define UBO_ITEM_RADIUS (ubo_layout()->item_radius)
#define UBO_PAGE_SIZE   3 /* fixed: L1/L2/L3 */

/* Font accessor macros (responsive; were hard-coded lv_font_montserrat_* /
 * ubo_font_icon_*). */
#define UBO_FONT_XS     (ubo_layout()->f_xs)
#define UBO_FONT_SM     (ubo_layout()->f_sm)
#define UBO_FONT_MD     (ubo_layout()->f_md)
#define UBO_FONT_LG     (ubo_layout()->f_lg)
#define UBO_FONT_XL     (ubo_layout()->f_xl)
#define UBO_FONT_XXL    (ubo_layout()->f_xxl)
#define UBO_FONT_ICON   (ubo_layout()->f_icon)
#define UBO_FONT_ICON_SM (ubo_layout()->f_icon_sm)

/* ---- Palette (see ubo_gui constants) ---- */
#define UBO_COL_BG      lv_color_hex(0x000000)
#define UBO_COL_FG      lv_color_hex(0xFFFFFF)
#define UBO_COL_MUTED   lv_color_hex(0x808080)
#define UBO_COL_INFO    lv_color_hex(0x2196F3)
#define UBO_COL_SUCCESS lv_color_hex(0x03F7AE)
#define UBO_COL_CPU     lv_color_hex(0x24D636)
#define UBO_COL_RAM     lv_color_hex(0xD68F24)
#define UBO_COL_SELECT  lv_color_hex(0x303030)
#define UBO_COL_DIVIDER lv_color_hex(0x303030)

/* Parse "#RRGGBB" (or NULL) into an lv_color_t, returning `fallback` if unset. */
lv_color_t ubo_parse_color(const char *hex, lv_color_t fallback);

/* ---- Persistent chrome ---- */
void ubo_screen_ensure(void);              /* build header/content/footer once   */
lv_obj_t *ubo_screen_content(void);        /* full-screen page built into by views */
lv_obj_t *ubo_screen_band_box(void);       /* container confined to the middle band */
void ubo_screen_clear_content(void);       /* stash current page, start a new one */
void ubo_screen_transition(int dx, int dy); /* animate new page in from (dx,dy)   */
void ubo_screen_show_chrome(bool show_header, bool show_footer);
void ubo_screen_set_title(const char *title);

/* Re-apply the most recently received status bar (used after a view rebuild). */
void ubo_status_bar_reapply(void);
void ubo_status_bar_apply(const ubo_status_bar *s); /* cache + render */
const char *ubo_status_bar_title(void);             /* cached hostname/title */

/* Build one menu item "bar" (right-rounded, ubo_gui dimensions). In short mode
 * it is icon-only and SHORT_W wide (home strip); otherwise full width with
 * icon + label. */
lv_obj_t *ubo_item_bar(lv_obj_t *parent, const ubo_menu_item *it, bool short_mode);

/* Show/position the persistent page-position slider (thin track + marker) on
 * the fixed content area so it stays still during page transitions; only the
 * marker moves. No-op / hidden when total_pages <= 1. */
void ubo_screen_set_page_slider(int page_index, int total_pages);

/* ---- Per-view builders (fill the content region) ---- */
void ubo_build_menu(const ubo_menu_view *v);
void ubo_build_home(const ubo_home_view *v);
void ubo_build_notification(const ubo_notification_view *v);
void ubo_build_instruction(const ubo_instruction_view *v);
void ubo_build_prompt(const ubo_prompt_view *v);
void ubo_build_application(const ubo_application_view *v);
void ubo_build_render(const ubo_render_view *v);

/* Look up a generic render-view prop by key; returns NULL when absent. */
const char *ubo_render_prop_get(const ubo_render_view *v, const char *key);

/* The image_viewer/frame_stream lv_image that frame updates write to (or NULL).
 * Set by the render builder; cleared on every content rebuild. */
void ubo_screen_set_frame_target(lv_obj_t *img);
lv_obj_t *ubo_screen_frame_target(void);

/* Convert a raw RGB888 (3 bytes/px) frame to the panel format and blit it into
 * the current frame target. No-op when there is no frame target. */
void ubo_render_update_frame(const uint8_t *rgb, int32_t w, int32_t h);

/* Forget the active render widget's interaction state (called on every content
 * rebuild). Scroll/choose route to the current render widget only. */
void ubo_render_reset(void);
void ubo_render_scroll(const char *direction); /* "up"/"down" on current widget */
void ubo_render_choose(int index);             /* L1/L2/L3 on current widget    */

/* ---- Top-layer overlays ---- */
void ubo_overlay_splash_show(void);
void ubo_overlay_splash_hide(void);
void ubo_overlay_blank(bool on);          /* full black cover */
void ubo_overlay_disconnected(bool shown); /* red "Disconnected" cover */
/* Show the disconnect cover with a reconnect countdown subtitle. */
void ubo_overlay_disconnected_status(int attempt, int max_attempts, int seconds);

#endif /* UBO_VIEWS_H */
