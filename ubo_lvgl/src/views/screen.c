/**
 * @file screen.c
 * Persistent screen chrome (header / content / footer) and the status bar.
 * The chrome is built once; per-view builders only refill the content region,
 * so the status bar survives view changes (as in the Kivy client).
 */
#include "ubo_views.h"

#include <stdio.h>
#include <string.h>

static lv_obj_t *s_header;
static lv_obj_t *s_title_lbl;
static lv_obj_t *s_content; /* fixed middle area */
static lv_obj_t *s_page;    /* current page (built into by views) */
static lv_obj_t *s_prev;    /* outgoing page during a transition */
static lv_obj_t *s_footer;
static lv_obj_t *s_clock_lbl;
static lv_obj_t *s_temp_lbl;
static lv_obj_t *s_footer_icons; /* right-aligned status icon strip */
static lv_obj_t *s_slider_track;  /* persistent page-position slider (stays put) */
static lv_obj_t *s_slider_marker;

/* Cached status bar so a content rebuild can re-apply it. */
static char s_clock[16];
static bool s_has_temp;
static double s_temp;
static char s_title_cache[80];

lv_color_t ubo_parse_color(const char *hex, lv_color_t fallback)
{
    if (!hex || hex[0] != '#' || strlen(hex) < 7) {
        return fallback;
    }
    unsigned int r = 0, g = 0, b = 0;
    if (sscanf(hex + 1, "%02x%02x%02x", &r, &g, &b) != 3) {
        return fallback;
    }
    return lv_color_make((uint8_t)r, (uint8_t)g, (uint8_t)b);
}

static void style_bar(lv_obj_t *o)
{
    lv_obj_remove_style_all(o);
    lv_obj_set_style_bg_color(o, UBO_COL_BG, 0);
    lv_obj_set_style_bg_opa(o, LV_OPA_COVER, 0);
    lv_obj_set_style_pad_all(o, 0, 0);
    lv_obj_clear_flag(o, LV_OBJ_FLAG_SCROLLABLE);
}

/* A transparent full-area page that view builders fill. */
static lv_obj_t *make_page(void)
{
    lv_obj_t *p = lv_obj_create(s_content);
    lv_obj_remove_style_all(p);
    lv_obj_set_size(p, lv_pct(100), lv_pct(100));
    lv_obj_set_pos(p, 0, 0);
    lv_obj_clear_flag(p, LV_OBJ_FLAG_SCROLLABLE);
    return p;
}

void ubo_screen_ensure(void)
{
    if (s_content) {
        return;
    }

    lv_obj_t *scr = lv_screen_active();
    lv_obj_remove_style_all(scr);
    lv_obj_set_style_bg_color(scr, UBO_COL_BG, 0);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, 0);
    lv_obj_clear_flag(scr, LV_OBJ_FLAG_SCROLLABLE);

    /* Full-screen content area + first page. The header/footer are created
     * afterwards so they overlay the content: views always lay out in the
     * middle band (between header and footer), and paginated menus let adjacent
     * items peek into the header/footer space, covered by the bars when shown. */
    s_content = lv_obj_create(scr);
    style_bar(s_content);
    lv_obj_set_size(s_content, UBO_W, UBO_H);
    lv_obj_set_pos(s_content, 0, 0);
    s_page = make_page();

    /* Header (overlays the content). */
    s_header = lv_obj_create(scr);
    style_bar(s_header);
    lv_obj_set_size(s_header, UBO_W, UBO_HEADER_H);
    lv_obj_set_pos(s_header, 0, 0);

    s_title_lbl = lv_label_create(s_header);
    lv_obj_set_style_text_color(s_title_lbl, UBO_COL_FG, 0);
    /* Titles carry a leading Nerd-Font icon glyph (e.g. U+F035C) followed by
     * text, so use the icon font (ArimoNerd has both icons and Latin). */
    lv_obj_set_style_text_font(s_title_lbl, ubo_font_icon_18(), 0);
    lv_label_set_long_mode(s_title_lbl, LV_LABEL_LONG_DOT);
    lv_obj_set_width(s_title_lbl, UBO_W - 16);
    lv_obj_set_style_text_align(s_title_lbl, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_center(s_title_lbl);
    lv_label_set_text(s_title_lbl, "");

    /* Footer (overlays the content). Left group: clock + temperature.
     * Right group: status icons (globe, mic, wifi/ethernet, ...). */
    s_footer = lv_obj_create(scr);
    style_bar(s_footer);
    lv_obj_set_size(s_footer, UBO_W, UBO_FOOTER_H);
    lv_obj_set_pos(s_footer, 0, UBO_H - UBO_FOOTER_H);

    lv_obj_t *left = lv_obj_create(s_footer);
    lv_obj_remove_style_all(left);
    lv_obj_clear_flag(left, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_size(left, LV_SIZE_CONTENT, lv_pct(100));
    lv_obj_align(left, LV_ALIGN_LEFT_MID, 6, 0);
    lv_obj_set_flex_flow(left, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(left, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(left, 6, 0);

    s_clock_lbl = lv_label_create(left);
    lv_obj_set_style_text_color(s_clock_lbl, UBO_COL_FG, 0);
    lv_obj_set_style_text_font(s_clock_lbl, &lv_font_montserrat_14, 0);
    lv_label_set_text(s_clock_lbl, "");

    s_temp_lbl = lv_label_create(left);
    lv_obj_set_style_text_color(s_temp_lbl, UBO_COL_MUTED, 0);
    lv_obj_set_style_text_font(s_temp_lbl, &lv_font_montserrat_14, 0);
    lv_label_set_text(s_temp_lbl, "");

    s_footer_icons = lv_obj_create(s_footer);
    lv_obj_remove_style_all(s_footer_icons);
    lv_obj_clear_flag(s_footer_icons, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_size(s_footer_icons, LV_SIZE_CONTENT, lv_pct(100));
    lv_obj_align(s_footer_icons, LV_ALIGN_RIGHT_MID, -6, 0);
    lv_obj_set_flex_flow(s_footer_icons, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(s_footer_icons, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(s_footer_icons, 5, 0);
}

lv_obj_t *ubo_screen_content(void)
{
    ubo_screen_ensure();
    return s_page;
}

lv_obj_t *ubo_screen_band_box(void)
{
    ubo_screen_ensure();
    /* A container confined to the middle band (between header and footer) for
     * views that should not bleed into the header/footer space. */
    lv_obj_t *box = lv_obj_create(s_page);
    lv_obj_remove_style_all(box);
    lv_obj_clear_flag(box, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_size(box, UBO_W, UBO_CONTENT_H);
    lv_obj_set_pos(box, 0, UBO_HEADER_H);
    return box;
}

void ubo_screen_clear_content(void)
{
    ubo_screen_ensure();
    /* Hide the page slider by default; paginated views re-show it. */
    if (s_slider_track) {
        lv_obj_add_flag(s_slider_track, LV_OBJ_FLAG_HIDDEN);
    }
    /* Stash the current page as outgoing and start a fresh one. The render
     * wrapper calls ubo_screen_transition() afterwards to animate (or to drop
     * the outgoing page immediately when no transition is requested). */
    if (s_prev) {
        lv_obj_del(s_prev);
    }
    s_prev = s_page;
    s_page = make_page();
}

static void marker_anim_y_cb(void *obj, int32_t v)
{
    lv_obj_set_y(obj, v);
}

void ubo_screen_set_page_slider(int page_index, int total_pages)
{
    ubo_screen_ensure();
    if (total_pages <= 1) {
        if (s_slider_track) {
            lv_obj_add_flag(s_slider_track, LV_OBJ_FLAG_HIDDEN);
        }
        return;
    }

    const int32_t track_h = UBO_CONTENT_H - 12;
    const int32_t marker_h = 18;

    /* The track is a child of the fixed content area (not the page), so it
     * stays still while pages slide underneath; only the marker moves. */
    if (!s_slider_track) {
        s_slider_track = lv_obj_create(s_content);
        lv_obj_remove_style_all(s_slider_track);
        lv_obj_clear_flag(s_slider_track, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_set_size(s_slider_track, 3, track_h);
        lv_obj_align(s_slider_track, LV_ALIGN_RIGHT_MID, -3, 0);
        lv_obj_set_style_radius(s_slider_track, 2, 0);
        lv_obj_set_style_bg_color(s_slider_track, lv_color_hex(0xABA7A7), 0);
        lv_obj_set_style_bg_opa(s_slider_track, LV_OPA_COVER, 0);

        s_slider_marker = lv_obj_create(s_slider_track);
        lv_obj_remove_style_all(s_slider_marker);
        lv_obj_clear_flag(s_slider_marker, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_set_size(s_slider_marker, 9, marker_h);
        lv_obj_set_x(s_slider_marker, (3 - 9) / 2); /* centre on the 3px track */
        lv_obj_set_style_radius(s_slider_marker, 4, 0);
        lv_obj_set_style_bg_color(s_slider_marker, lv_color_hex(0x68B7FF), 0);
        lv_obj_set_style_bg_opa(s_slider_marker, LV_OPA_COVER, 0);
    }

    lv_obj_clear_flag(s_slider_track, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(s_slider_track); /* keep above the sliding pages */

    const int32_t range = track_h - marker_h;
    int idx = page_index;
    if (idx < 0) {
        idx = 0;
    }
    if (idx > total_pages - 1) {
        idx = total_pages - 1;
    }
    const int32_t target_y = (int32_t)((long)idx * range / (total_pages - 1));

    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_var(&a, s_slider_marker);
    lv_anim_set_exec_cb(&a, marker_anim_y_cb);
    lv_anim_set_values(&a, lv_obj_get_y(s_slider_marker), target_y);
    lv_anim_set_time(&a, 200);
    lv_anim_set_path_cb(&a, lv_anim_path_ease_out);
    lv_anim_start(&a);
}

static void anim_x_cb(void *obj, int32_t v)
{
    lv_obj_set_x(obj, v);
}

static void anim_y_cb(void *obj, int32_t v)
{
    lv_obj_set_y(obj, v);
}

static void prev_done_cb(lv_anim_t *a)
{
    if (a->var == s_prev) {
        s_prev = NULL;
    }
    lv_obj_del(a->var);
}

void ubo_screen_transition(int dx, int dy)
{
    ubo_screen_ensure();
    if (dx == 0 && dy == 0) {
        if (s_prev) {
            lv_obj_del(s_prev);
            s_prev = NULL;
        }
        return;
    }

    lv_anim_exec_xcb_t cb = dx ? anim_x_cb : anim_y_cb;
    const int32_t off = dx ? dx : dy;

    /* Incoming page slides from off-screen to 0. */
    if (dx) {
        lv_obj_set_x(s_page, off);
    } else {
        lv_obj_set_y(s_page, off);
    }
    lv_anim_t in;
    lv_anim_init(&in);
    lv_anim_set_var(&in, s_page);
    lv_anim_set_exec_cb(&in, cb);
    lv_anim_set_values(&in, off, 0);
    lv_anim_set_time(&in, 200);
    lv_anim_set_path_cb(&in, lv_anim_path_ease_out);
    lv_anim_start(&in);

    /* Outgoing page slides the opposite way, then is deleted. */
    if (s_prev) {
        lv_anim_t out;
        lv_anim_init(&out);
        lv_anim_set_var(&out, s_prev);
        lv_anim_set_exec_cb(&out, cb);
        lv_anim_set_values(&out, 0, -off);
        lv_anim_set_time(&out, 200);
        lv_anim_set_path_cb(&out, lv_anim_path_ease_out);
        lv_anim_set_ready_cb(&out, prev_done_cb);
        lv_anim_start(&out);
    }
}

void ubo_screen_show_chrome(bool show_header, bool show_footer)
{
    ubo_screen_ensure();
    /* The content area is always full-screen; we only toggle the header/footer
     * bars (independently). Header shows on the first page, footer on the last,
     * so middle pages reveal the peeking items above/below. */
    if (show_header) {
        lv_obj_clear_flag(s_header, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(s_header, LV_OBJ_FLAG_HIDDEN);
    }
    if (show_footer) {
        lv_obj_clear_flag(s_footer, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(s_footer, LV_OBJ_FLAG_HIDDEN);
    }
}

void ubo_screen_set_title(const char *title)
{
    ubo_screen_ensure();
    lv_label_set_text(s_title_lbl, title ? title : "");
}

void ubo_status_bar_reapply(void)
{
    ubo_screen_ensure();
    lv_label_set_text(s_clock_lbl, s_clock);
    if (s_has_temp) {
        char buf[16];
        snprintf(buf, sizeof(buf), "%.0f\xC2\xB0", s_temp); /* trailing degree */
        lv_label_set_text(s_temp_lbl, buf);
    } else {
        lv_label_set_text(s_temp_lbl, "");
    }
}

void ubo_status_bar_apply(const ubo_status_bar *s)
{
    ubo_screen_ensure();
    if (!s) {
        return;
    }
    snprintf(s_clock, sizeof(s_clock), "%s", s->clock ? s->clock : "");
    snprintf(s_title_cache, sizeof(s_title_cache), "%s", s->title ? s->title : "");
    s_has_temp = s->has_temperature;
    s_temp = s->temperature;

    /* Rebuild the footer status-icon strip. Match ubo_gui: reversed order,
     * at most 4 icons (the right-most strip). */
    lv_obj_clean(s_footer_icons);
    int rendered = 0;
    for (int i = s->icon_count - 1; i >= 0 && rendered < 4; i--) {
        const ubo_status_icon *ic = &s->icons[i];
        if (!ic->symbol || !ic->symbol[0]) {
            continue;
        }
        lv_obj_t *l = lv_label_create(s_footer_icons);
        lv_obj_set_style_text_font(l, ubo_font_icon_18(), 0);
        lv_obj_set_style_text_color(l, ubo_parse_color(ic->color, UBO_COL_FG), 0);
        lv_label_set_text(l, ic->symbol);
        rendered++;
    }

    ubo_status_bar_reapply();
}

const char *ubo_status_bar_title(void)
{
    return s_title_cache;
}
