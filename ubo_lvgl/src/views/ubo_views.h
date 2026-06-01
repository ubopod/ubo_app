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

/* ---- Layout constants (240x240 panel; values mirror ubo_gui) ---- */
#define UBO_W 240
#define UBO_H 240
#define UBO_HEADER_H 34 /* ubo_gui app.kv header */
#define UBO_FOOTER_H 36 /* ubo_gui app.kv footer */
#define UBO_CONTENT_H (UBO_H - UBO_HEADER_H - UBO_FOOTER_H) /* 170 */
#define UBO_PAGE_SIZE 3
#define UBO_ITEM_H 52    /* ubo_gui MENU_ITEM_HEIGHT */
#define UBO_ITEM_GAP 7   /* ubo_gui MENU_ITEM_GAP     */
#define UBO_SHORT_W 46   /* ubo_gui SHORT_WIDTH       */
#define UBO_ITEM_RADIUS 26 /* ubo_gui: right corners rounded, left squared */

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

/* ---- Top-layer overlays ---- */
void ubo_overlay_splash_show(void);
void ubo_overlay_splash_hide(void);
void ubo_overlay_blank(bool on);          /* full black cover */
void ubo_overlay_disconnected(bool shown); /* red "Disconnected" cover */
/* Show the disconnect cover with a reconnect countdown subtitle. */
void ubo_overlay_disconnected_status(int attempt, int max_attempts, int seconds);

#endif /* UBO_VIEWS_H */
