/**
 * @file view_render.c
 * Generic RenderViewData widgets. The core sends a `kind` (e.g. "text_viewer",
 * "status", "qr_code", "qr_code_carousel") plus a flat `props` map; this file
 * dispatches on `kind` and builds the matching LVGL widget tree — the analogue
 * of ubo_gui's GENERIC_RENDER_WIDGETS. Binary widgets (image_viewer,
 * frame_stream) fall through to a placeholder for now.
 */
#include "ubo_views.h"

#include <stdlib.h>
#include <string.h>

const char *ubo_render_prop_get(const ubo_render_view *v, const char *key)
{
    for (int i = 0; i < v->prop_count; i++) {
        if (v->props[i].key && strcmp(v->props[i].key, key) == 0) {
            return v->props[i].value;
        }
    }
    return NULL;
}

/* List-valued props are newline-joined; split helpers for the QR carousel. */
static int count_lines(const char *s)
{
    if (!s || !s[0]) {
        return 0;
    }
    int n = 1;
    for (const char *p = s; *p; p++) {
        if (*p == '\n') {
            n++;
        }
    }
    return n;
}

static void nth_line(const char *s, int idx, char *out, size_t out_sz)
{
    out[0] = '\0';
    if (!s) {
        return;
    }
    int line = 0;
    const char *start = s;
    for (const char *p = s;; p++) {
        if (*p == '\n' || *p == '\0') {
            if (line == idx) {
                size_t len = (size_t)(p - start);
                if (len >= out_sz) {
                    len = out_sz - 1;
                }
                memcpy(out, start, len);
                out[len] = '\0';
                return;
            }
            if (*p == '\0') {
                return;
            }
            line++;
            start = p + 1;
        }
    }
}

static lv_obj_t *column(lv_obj_t *parent)
{
    lv_obj_set_flex_flow(parent, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(parent, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_row(parent, 6, 0);
    return parent;
}

static void build_text_viewer(const ubo_render_view *v)
{
    const char *text = ubo_render_prop_get(v, "text");
    lv_obj_t *c = ubo_screen_content();
    lv_obj_set_style_pad_all(c, 6, 0);

    /* A vertically scrollable container with a wrapped label. (Local UP/DOWN
     * scrolling is wired with the application-scroll events; see roadmap.) */
    lv_obj_t *scroll = lv_obj_create(c);
    lv_obj_remove_style_all(scroll);
    lv_obj_set_size(scroll, lv_pct(100), lv_pct(100));
    lv_obj_set_scroll_dir(scroll, LV_DIR_VER);

    lv_obj_t *lbl = lv_label_create(scroll);
    lv_label_set_long_mode(lbl, LV_LABEL_LONG_WRAP);
    lv_obj_set_width(lbl, lv_pct(100));
    lv_obj_set_style_text_font(lbl, &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_color(lbl, UBO_COL_FG, 0);
    lv_label_set_text(lbl, text ? text : "");
}

static void build_status(const ubo_render_view *v)
{
    const char *icon = ubo_render_prop_get(v, "icon");
    const char *text = ubo_render_prop_get(v, "text");
    lv_obj_t *c = column(ubo_screen_content());
    lv_obj_set_style_pad_row(c, 10, 0);

    if (icon && icon[0]) {
        lv_obj_t *ic = lv_label_create(c);
        /* Largest icon font we ship is 18px; a dedicated large icon font is a
         * follow-up for full parity with ubo_gui's 56px status icon. */
        lv_obj_set_style_text_font(ic, ubo_font_icon_18(), 0);
        lv_obj_set_style_text_color(ic, UBO_COL_FG, 0);
        lv_label_set_text(ic, icon);
    }
    if (text && text[0]) {
        lv_obj_t *t = lv_label_create(c);
        lv_label_set_long_mode(t, LV_LABEL_LONG_WRAP);
        lv_obj_set_width(t, lv_pct(90));
        lv_obj_set_style_text_align(t, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_set_style_text_font(t, &lv_font_montserrat_20, 0);
        lv_obj_set_style_text_color(t, UBO_COL_FG, 0);
        lv_label_set_text(t, text);
    }
}

static void build_qr(lv_obj_t *parent, const char *value, const char *label)
{
    lv_obj_t *qr = lv_qrcode_create(parent);
    lv_qrcode_set_size(qr, 132);
    lv_qrcode_set_dark_color(qr, lv_color_black());
    lv_qrcode_set_light_color(qr, lv_color_white());
    if (value && value[0]) {
        lv_qrcode_update(qr, value, (uint32_t)strlen(value));
    }
    /* White quiet zone so the panel's black background doesn't crowd the code. */
    lv_obj_set_style_border_color(qr, lv_color_white(), 0);
    lv_obj_set_style_border_width(qr, 4, 0);

    if (label && label[0]) {
        lv_obj_t *l = lv_label_create(parent);
        lv_label_set_long_mode(l, LV_LABEL_LONG_WRAP);
        lv_obj_set_width(l, lv_pct(90));
        lv_obj_set_style_text_align(l, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_set_style_text_font(l, &lv_font_montserrat_14, 0);
        lv_obj_set_style_text_color(l, UBO_COL_FG, 0);
        lv_label_set_text(l, label);
    }
}

static void build_qr_carousel(const ubo_render_view *v)
{
    const char *values = ubo_render_prop_get(v, "values");
    const char *labels = ubo_render_prop_get(v, "labels");
    const char *idx_s = ubo_render_prop_get(v, "index");
    const int total = count_lines(values);
    int idx = idx_s ? atoi(idx_s) : 0;
    if (total > 0) {
        idx = ((idx % total) + total) % total;
    }

    char val[1024];
    char lab[256];
    nth_line(values, idx, val, sizeof(val));
    nth_line(labels, idx, lab, sizeof(lab));

    lv_obj_t *c = column(ubo_screen_content());
    build_qr(c, val, lab[0] ? lab : NULL);
    if (total > 1) {
        lv_obj_t *pos = lv_label_create(c);
        lv_obj_set_style_text_font(pos, &lv_font_montserrat_12, 0);
        lv_obj_set_style_text_color(pos, UBO_COL_MUTED, 0);
        lv_label_set_text_fmt(pos, "%d / %d", idx + 1, total);
    }
}

/* image_viewer / frame_stream: a centred lv_image fed by ubo_render_update_frame
 * (one-shot for image_viewer, repeatedly for frame_stream). */
static lv_image_dsc_t s_frame_dsc;
static uint16_t *s_frame_buf;
static lv_obj_t *s_frame_hint;

static void build_frame_view(bool stream)
{
    lv_obj_t *c = ubo_screen_content();
    lv_obj_set_flex_flow(c, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(c, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER);

    lv_obj_t *img = lv_image_create(c);
    lv_obj_center(img);
    ubo_screen_set_frame_target(img);

    /* Hint shown until the first frame lands (mainly for the live stream). */
    s_frame_hint = lv_label_create(c);
    lv_obj_set_style_text_color(s_frame_hint, UBO_COL_MUTED, 0);
    lv_obj_set_style_text_font(s_frame_hint, &lv_font_montserrat_14, 0);
    lv_label_set_text(s_frame_hint, stream ? "Waiting for video..." : "");
}

void ubo_render_update_frame(const uint8_t *rgb, int32_t w, int32_t h)
{
    lv_obj_t *img = ubo_screen_frame_target();
    if (!img || !rgb || w <= 0 || h <= 0) {
        return;
    }
    const size_t n = (size_t)w * (size_t)h;
    uint16_t *buf = realloc(s_frame_buf, n * 2);
    if (!buf) {
        return;
    }
    s_frame_buf = buf;
    for (size_t i = 0; i < n; i++) {
        const uint8_t r = rgb[i * 3];
        const uint8_t g = rgb[i * 3 + 1];
        const uint8_t b = rgb[i * 3 + 2];
        s_frame_buf[i] =
            (uint16_t)(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3));
    }
    memset(&s_frame_dsc, 0, sizeof(s_frame_dsc));
    s_frame_dsc.header.cf = LV_COLOR_FORMAT_RGB565;
    s_frame_dsc.header.w = (uint32_t)w;
    s_frame_dsc.header.h = (uint32_t)h;
    s_frame_dsc.header.stride = (uint32_t)w * 2;
    s_frame_dsc.data = (const uint8_t *)s_frame_buf;
    s_frame_dsc.data_size = (uint32_t)(n * 2);
    lv_image_set_src(img, &s_frame_dsc);

    /* Scale to fit the panel while keeping aspect ratio. */
    int32_t sx = (int32_t)((long)UBO_W * 256 / w);
    int32_t sy = (int32_t)((long)UBO_H * 256 / h);
    int32_t scale = sx < sy ? sx : sy;
    if (scale > 256) {
        scale = 256; /* don't upscale past 1:1 */
    }
    lv_image_set_scale(img, (uint16_t)scale);
    lv_obj_center(img);

    if (s_frame_hint) {
        lv_obj_add_flag(s_frame_hint, LV_OBJ_FLAG_HIDDEN);
    }
}

static void build_placeholder(const char *kind)
{
    lv_obj_t *c = column(ubo_screen_content());
    lv_obj_t *l = lv_label_create(c);
    lv_obj_set_style_text_align(l, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_text_color(l, UBO_COL_MUTED, 0);
    lv_obj_set_style_text_font(l, &lv_font_montserrat_16, 0);
    lv_label_set_text(l, (kind && kind[0]) ? kind : "render");
}

void ubo_build_render(const ubo_render_view *v)
{
    ubo_screen_show_chrome(v->show_status_bar, v->show_status_bar);
    ubo_screen_set_title((v->title && v->title[0]) ? v->title : "");
    ubo_screen_clear_content();

    const char *kind = v->kind ? v->kind : "";
    if (strcmp(kind, "text_viewer") == 0) {
        build_text_viewer(v);
    } else if (strcmp(kind, "status") == 0) {
        build_status(v);
    } else if (strcmp(kind, "qr_code") == 0) {
        build_qr(column(ubo_screen_content()), ubo_render_prop_get(v, "value"),
                 ubo_render_prop_get(v, "label"));
    } else if (strcmp(kind, "qr_code_carousel") == 0) {
        build_qr_carousel(v);
    } else if (strcmp(kind, "image_viewer") == 0) {
        build_frame_view(false);
    } else if (strcmp(kind, "frame_stream") == 0) {
        build_frame_view(true);
    } else {
        build_placeholder(kind);
    }

    ubo_status_bar_reapply();
}
