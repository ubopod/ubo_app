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
static lv_obj_t *s_header_progress; /* left: progress-notification ring/spinner strip */
static lv_obj_t *s_header_signs;    /* right: recording/replaying signs (flex row) */
static lv_obj_t *s_record_sign;     /* recording / audio-recording indicator (blinks) */
static lv_obj_t *s_replay_sign;     /* replaying indicator (blinks) */
static lv_obj_t *s_content; /* fixed middle area */
static lv_obj_t *s_page;    /* current page (built into by views) */
static lv_obj_t *s_prev;    /* outgoing page during a transition */
static lv_obj_t *s_footer;
static lv_obj_t *s_clock_lbl;
static lv_obj_t *s_temp_lbl;
static lv_obj_t *s_light_lbl;    /* ambient light glyph (opacity tracks level) */
static lv_obj_t *s_footer_icons; /* right-aligned status icon strip */
static lv_obj_t *s_slider_track;  /* persistent page-position slider (stays put) */
static lv_obj_t *s_slider_marker;
static lv_obj_t *s_frame_img;     /* current image_viewer/frame_stream target */

/* Nerd-Font glyphs (same codepoints ubo_gui menu_header/footer use). */
#define GLYPH_RECORD "\xF3\xB0\x91\x8A" /* U+F044A record */
#define GLYPH_REPLAY "\xF3\xB0\x91\x99" /* U+F0459 play   */
#define GLYPH_LIGHT  "\xF3\xB1\xA9\x8E" /* U+F1A4E brightness */

/* Cached status bar so a content rebuild can re-apply it. */
static char s_clock[16];
static bool s_has_temp;
static double s_temp;
static bool s_has_light;
static double s_light;
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

/* Blink a sign label like ubo_gui's sign_animation: hold visible ~1s, fade out,
 * hold hidden ~0.5s, fade back in, repeat. */
static void blink_opa_cb(void *obj, int32_t v)
{
    lv_obj_set_style_opa((lv_obj_t *)obj, (lv_opa_t)v, 0);
}

static void start_blink(lv_obj_t *o)
{
    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_var(&a, o);
    lv_anim_set_exec_cb(&a, blink_opa_cb);
    lv_anim_set_values(&a, LV_OPA_COVER, LV_OPA_TRANSP);
    lv_anim_set_time(&a, 100);          /* fade out */
    lv_anim_set_playback_time(&a, 100); /* fade back in */
    lv_anim_set_repeat_delay(&a, 1000); /* hold visible before fading out */
    lv_anim_set_playback_delay(&a, 500); /* hold hidden before fading in  */
    lv_anim_set_repeat_count(&a, LV_ANIM_REPEAT_INFINITE);
    lv_anim_start(&a);
}

/* Show/hide a blinking sign (matches ubo_gui _update_sign_widget). */
static void update_sign(lv_obj_t *sign, bool show, lv_color_t color)
{
    if (show) {
        lv_obj_set_style_text_color(sign, color, 0);
        if (lv_obj_has_flag(sign, LV_OBJ_FLAG_HIDDEN)) {
            lv_obj_clear_flag(sign, LV_OBJ_FLAG_HIDDEN);
            lv_obj_set_style_opa(sign, LV_OPA_COVER, 0);
            start_blink(sign);
        }
    } else if (!lv_obj_has_flag(sign, LV_OBJ_FLAG_HIDDEN)) {
        lv_anim_del(sign, blink_opa_cb);
        lv_obj_set_style_opa(sign, LV_OPA_COVER, 0);
        lv_obj_add_flag(sign, LV_OBJ_FLAG_HIDDEN);
    }
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
    lv_obj_set_style_text_font(s_title_lbl, UBO_FONT_ICON, 0);
    lv_label_set_long_mode(s_title_lbl, LV_LABEL_LONG_DOT);
    lv_obj_set_width(s_title_lbl, UBO_W - 16);
    lv_obj_set_style_text_align(s_title_lbl, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_center(s_title_lbl);
    lv_label_set_text(s_title_lbl, "");

    /* Header left: progress-notification indicators (ring / spinner), overlaid
     * on the title's left edge (matches ubo_gui menu_header progress_layout). */
    s_header_progress = lv_obj_create(s_header);
    lv_obj_remove_style_all(s_header_progress);
    lv_obj_clear_flag(s_header_progress, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_size(s_header_progress, LV_SIZE_CONTENT, lv_pct(100));
    lv_obj_align(s_header_progress, LV_ALIGN_LEFT_MID, 4, 0);
    lv_obj_set_flex_flow(s_header_progress, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(s_header_progress, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(s_header_progress, 3, 0);

    /* Header right: recording / replaying signs (blink while active). Hidden
     * children are ignored by the flex layout, so they stack cleanly. */
    s_header_signs = lv_obj_create(s_header);
    lv_obj_remove_style_all(s_header_signs);
    lv_obj_clear_flag(s_header_signs, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_size(s_header_signs, LV_SIZE_CONTENT, lv_pct(100));
    lv_obj_align(s_header_signs, LV_ALIGN_RIGHT_MID, -4, 0);
    lv_obj_set_flex_flow(s_header_signs, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(s_header_signs, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(s_header_signs, 2, 0);

    s_record_sign = lv_label_create(s_header_signs);
    lv_obj_set_style_text_font(s_record_sign, UBO_FONT_ICON, 0);
    lv_label_set_text(s_record_sign, GLYPH_RECORD);
    lv_obj_add_flag(s_record_sign, LV_OBJ_FLAG_HIDDEN);

    s_replay_sign = lv_label_create(s_header_signs);
    lv_obj_set_style_text_font(s_replay_sign, UBO_FONT_ICON, 0);
    lv_label_set_text(s_replay_sign, GLYPH_REPLAY);
    lv_obj_add_flag(s_replay_sign, LV_OBJ_FLAG_HIDDEN);

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
    lv_obj_set_style_text_font(s_clock_lbl, UBO_FONT_SM, 0);
    lv_label_set_text(s_clock_lbl, "");

    s_temp_lbl = lv_label_create(left);
    lv_obj_set_style_text_color(s_temp_lbl, UBO_COL_MUTED, 0);
    lv_obj_set_style_text_font(s_temp_lbl, UBO_FONT_SM, 0);
    lv_label_set_text(s_temp_lbl, "");

    /* Ambient light glyph: opacity tracks the reading (bright env => brighter),
     * hidden when the device reports no light sensor (matches ubo_gui). */
    s_light_lbl = lv_label_create(left);
    lv_obj_set_style_text_font(s_light_lbl, UBO_FONT_ICON, 0);
    lv_obj_set_style_text_color(s_light_lbl, UBO_COL_FG, 0);
    lv_label_set_text(s_light_lbl, GLYPH_LIGHT);
    lv_obj_add_flag(s_light_lbl, LV_OBJ_FLAG_HIDDEN);

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

void ubo_screen_set_frame_target(lv_obj_t *img)
{
    s_frame_img = img;
}

lv_obj_t *ubo_screen_frame_target(void)
{
    return s_frame_img;
}

void ubo_screen_clear_content(void)
{
    ubo_screen_ensure();
    /* The outgoing page (and any frame image on it) is about to be replaced. */
    s_frame_img = NULL;
    ubo_render_reset(); /* drop the previous render widget's interaction state */
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

/* Update the ambient-light glyph from the cached reading: hidden when there is
 * no sensor, else opacity scales with the level (matches ubo_gui's /140 map). */
static void apply_light(void)
{
    if (!s_has_light) {
        lv_obj_add_flag(s_light_lbl, LV_OBJ_FLAG_HIDDEN);
        return;
    }
    double v = s_light;
    if (v < 0) {
        v = 0;
    }
    if (v > 140) {
        v = 140;
    }
    lv_obj_clear_flag(s_light_lbl, LV_OBJ_FLAG_HIDDEN);
    lv_obj_set_style_opa(s_light_lbl, (lv_opa_t)(v / 140.0 * 255.0), 0);
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
    apply_light();
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
    s_has_light = s->has_light;
    s_light = s->light_level;

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
        lv_obj_set_style_text_font(l, UBO_FONT_ICON, 0);
        lv_obj_set_style_text_color(l, ubo_parse_color(ic->color, UBO_COL_FG), 0);
        lv_label_set_text(l, ic->symbol);
        rendered++;
    }

    /* Recording / replaying indicators (header right). Match ubo_gui: the record
     * sign shows for is_recording OR is_recording_audio (blue when recording,
     * else green); the replay sign shows for is_replaying (green). */
    update_sign(s_record_sign, s->is_recording || s->is_recording_audio,
                s->is_recording ? lv_color_hex(0x0000FF) : lv_color_hex(0x00FF00));
    update_sign(s_replay_sign, s->is_replaying, lv_color_hex(0x00FF00));

    /* Progress notifications (header left): determinate => ring, else spinner. */
    lv_obj_clean(s_header_progress);
    for (int i = 0; i < s->progress_count; i++) {
        const ubo_progress_notification *pn = &s->progress_notifications[i];
        const lv_color_t col = ubo_parse_color(pn->color, UBO_COL_INFO);
        if (pn->has_progress) {
            lv_obj_t *arc = lv_arc_create(s_header_progress);
            lv_obj_set_size(arc, 22, 22);
            lv_obj_remove_style(arc, NULL, LV_PART_KNOB);
            lv_obj_clear_flag(arc, LV_OBJ_FLAG_CLICKABLE);
            lv_arc_set_rotation(arc, 270);
            lv_arc_set_bg_angles(arc, 0, 360);
            lv_arc_set_range(arc, 0, 100);
            lv_arc_set_value(arc, (int32_t)(pn->progress * 100.0 + 0.5));
            lv_obj_set_style_arc_width(arc, 3, LV_PART_MAIN);
            lv_obj_set_style_arc_width(arc, 3, LV_PART_INDICATOR);
            lv_obj_set_style_arc_color(arc, UBO_COL_MUTED, LV_PART_MAIN);
            lv_obj_set_style_arc_color(arc, col, LV_PART_INDICATOR);
        } else {
            lv_obj_t *sp = lv_spinner_create(s_header_progress);
            lv_obj_set_size(sp, 22, 22);
            lv_spinner_set_anim_params(sp, 1000, 270);
            lv_obj_set_style_arc_width(sp, 3, LV_PART_MAIN);
            lv_obj_set_style_arc_width(sp, 3, LV_PART_INDICATOR);
            lv_obj_set_style_arc_color(sp, UBO_COL_MUTED, LV_PART_MAIN);
            lv_obj_set_style_arc_color(sp, col, LV_PART_INDICATOR);
        }
    }

    ubo_status_bar_reapply();
}

const char *ubo_status_bar_title(void)
{
    return s_title_cache;
}
