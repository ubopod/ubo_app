/**
 * @file view_render.c
 * Generic RenderViewData widgets. The core sends a `kind` (e.g. "text_viewer",
 * "status", "qr_code", "qr_code_carousel", "readings") plus a flat `props` map;
 * this file dispatches on `kind` and builds the matching LVGL widget tree — the
 * analogue of ubo_gui's GENERIC_RENDER_WIDGETS. Binary widgets (image_viewer,
 * frame_stream) fall through to a placeholder for now.
 */
#include "ubo_views.h"

#include <stdio.h>
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

/* ---- Local interaction state (driven by ApplicationScroll/ChooseByIndex) ----
 * Only the active render widget reacts to UP/DOWN (scroll/cycle/zoom) and to
 * L1/L2/L3 (image-viewer mode switch). Reset on every content rebuild. */
enum { RW_NONE, RW_TEXT, RW_CAROUSEL, RW_IMAGE };
static int s_rw_kind;
static lv_obj_t *s_text_scroll;
static lv_obj_t *s_car_col;   /* carousel container to rebuild on cycle */
static char *s_car_values;    /* strdup'd newline-joined value/label lists */
static char *s_car_labels;
static int s_car_index;
static int s_car_total;
static lv_obj_t *s_img_obj;
static int s_img_mode;        /* 0=vertical pan, 1=horizontal pan, 2=zoom */
static int32_t s_img_scale;   /* current scale, 256 = 1:1 */
static int32_t s_img_fit;     /* fit-to-screen scale (zoom-out floor) */
static lv_obj_t *s_frame_hint; /* "waiting" hint, hidden once a frame lands */
static int32_t s_chunk_w, s_chunk_h; /* dims of the data in s_frame_buf */
static int32_t s_chunk_next_row;     /* rows of the in-progress frame assembled */
static bool s_chunk_ready;           /* s_frame_buf holds one complete frame */
static bool s_chunk_attached;        /* the live image object shows s_frame_dsc */

void ubo_render_reset(void)
{
    s_rw_kind = RW_NONE;
    s_text_scroll = NULL;
    s_car_col = NULL;
    free(s_car_values);
    s_car_values = NULL;
    free(s_car_labels);
    s_car_labels = NULL;
    s_car_index = 0;
    s_car_total = 0;
    s_img_obj = NULL;
    s_img_mode = 0;
    s_frame_hint = NULL;
    /* A rebuilt view gets a fresh image object, so the src must be set again --
     * but the assembled pixels survive: they are what `build_frame_view`
     * re-attaches when the view for a still finally appears. */
    s_chunk_attached = false;
}

static void build_text_viewer(const ubo_render_view *v)
{
    const char *text = ubo_render_prop_get(v, "text");
    lv_obj_t *c = ubo_screen_content();
    lv_obj_set_style_pad_all(c, 6, 0);

    /* A vertically scrollable container with a wrapped label; UP/DOWN scroll it
     * via the application-scroll events (see ubo_render_scroll). */
    lv_obj_t *scroll = lv_obj_create(c);
    lv_obj_remove_style_all(scroll);
    lv_obj_set_size(scroll, lv_pct(100), lv_pct(100));
    lv_obj_set_scroll_dir(scroll, LV_DIR_VER);

    lv_obj_t *lbl = lv_label_create(scroll);
    lv_label_set_long_mode(lbl, LV_LABEL_LONG_WRAP);
    lv_obj_set_width(lbl, lv_pct(100));
    lv_obj_set_style_text_font(lbl, UBO_FONT_SM, 0);
    lv_obj_set_style_text_color(lbl, UBO_COL_FG, 0);
    lv_label_set_text(lbl, text ? text : "");

    s_rw_kind = RW_TEXT;
    s_text_scroll = scroll;
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
        lv_obj_set_style_text_font(ic, UBO_FONT_ICON, 0);
        lv_obj_set_style_text_color(ic, UBO_COL_FG, 0);
        lv_label_set_text(ic, icon);
    }
    if (text && text[0]) {
        lv_obj_t *t = lv_label_create(c);
        lv_label_set_long_mode(t, LV_LABEL_LONG_WRAP);
        lv_obj_set_width(t, lv_pct(90));
        lv_obj_set_style_text_align(t, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_set_style_text_font(t, UBO_FONT_XL, 0);
        lv_obj_set_style_text_color(t, UBO_COL_FG, 0);
        lv_label_set_text(t, text);
    }
}

/* A label that only repeats the URL already encoded in the QR is not worth the
 * space here: this screen has no browser, so the URL cannot be followed, and
 * the text crowds out the code it duplicates. Labels that are not URLs — a
 * device code, an `ip:port` — are what the user actually has to read. */
static bool label_is_url(const char *s)
{
    return s && (strncmp(s, "http://", 7) == 0 || strncmp(s, "https://", 8) == 0);
}

static void build_qr(lv_obj_t *parent, const char *value, const char *label,
                     const char *caption)
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

    if (label && label[0] && !label_is_url(label)) {
        lv_obj_t *l = lv_label_create(parent);
        lv_label_set_long_mode(l, LV_LABEL_LONG_WRAP);
        lv_obj_set_width(l, lv_pct(90));
        lv_obj_set_style_text_align(l, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_set_style_text_font(l, UBO_FONT_SM, 0);
        lv_obj_set_style_text_color(l, UBO_COL_FG, 0);
        lv_label_set_text(l, label);
    }

    /* Its own line, larger than the label: a device code has to be readable
     * from across the room and typed by hand, unlike the URL above it. */
    if (caption && caption[0]) {
        lv_obj_t *c = lv_label_create(parent);
        lv_label_set_long_mode(c, LV_LABEL_LONG_WRAP);
        lv_obj_set_width(c, lv_pct(90));
        lv_obj_set_style_text_align(c, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_set_style_text_font(c, UBO_FONT_XL, 0);
        lv_obj_set_style_text_color(c, UBO_COL_FG, 0);
        lv_label_set_text(c, caption);
    }
}

/* (Re)build the carousel QR for the current index into the stored container. */
static void carousel_render(void)
{
    if (!s_car_col) {
        return;
    }
    lv_obj_clean(s_car_col);
    char val[1024];
    char lab[256];
    nth_line(s_car_values, s_car_index, val, sizeof(val));
    nth_line(s_car_labels, s_car_index, lab, sizeof(lab));
    /* The carousel has no per-item caption; its position indicator is added
     * below by the caller. */
    build_qr(s_car_col, val, lab[0] ? lab : NULL, NULL);
    if (s_car_total > 1) {
        lv_obj_t *pos = lv_label_create(s_car_col);
        lv_obj_set_style_text_font(pos, UBO_FONT_XS, 0);
        lv_obj_set_style_text_color(pos, UBO_COL_MUTED, 0);
        lv_label_set_text_fmt(pos, "%d / %d", s_car_index + 1, s_car_total);
    }
}

static void build_qr_carousel(const ubo_render_view *v)
{
    const char *values = ubo_render_prop_get(v, "values");
    const char *labels = ubo_render_prop_get(v, "labels");
    const char *idx_s = ubo_render_prop_get(v, "index");
    s_car_total = count_lines(values);
    int idx = idx_s ? atoi(idx_s) : 0;
    if (s_car_total > 0) {
        idx = ((idx % s_car_total) + s_car_total) % s_car_total;
    }
    s_car_index = idx;
    s_car_values = values ? strdup(values) : NULL;
    s_car_labels = labels ? strdup(labels) : NULL;
    s_car_col = column(ubo_screen_content());
    s_rw_kind = RW_CAROUSEL;
    carousel_render();
}

/* A label/value/unit table -- "Temperature      22.5 °C" -- the analogue of
 * ubo_gui's ReadingsRenderPage. `labels`, `values` and `units` are parallel
 * list props, so they arrive here newline-joined like the carousel's.
 *
 * The rows are rebuilt on every props update (1 Hz for a live sensor) rather
 * than re-texted in place like the Kivy widget does: a handful of labels is
 * cheap to rebuild, and the update path here already tears the content area
 * down before calling us. */
static void build_readings(const ubo_render_view *v)
{
    const char *labels = ubo_render_prop_get(v, "labels");
    const char *values = ubo_render_prop_get(v, "values");
    const char *units = ubo_render_prop_get(v, "units");
    const int rows = count_lines(labels);

    /* The band box, not the full-screen page: the header overlays the page, so
     * a top-aligned list built into it loses its first row behind the title. */
    lv_obj_t *c = ubo_screen_band_box();
    lv_obj_set_style_pad_all(c, UBO_SCALE(6), 0);

    if (rows == 0) {
        const char *placeholder = ubo_render_prop_get(v, "placeholder");
        lv_obj_t *l = lv_label_create(column(c));
        lv_label_set_long_mode(l, LV_LABEL_LONG_WRAP);
        lv_obj_set_width(l, lv_pct(90));
        lv_obj_set_style_text_align(l, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_set_style_text_font(l, UBO_FONT_SM, 0);
        lv_obj_set_style_text_color(l, UBO_COL_MUTED, 0);
        lv_label_set_text(l, (placeholder && placeholder[0]) ? placeholder
                                                            : "No readings yet");
        return;
    }

    lv_obj_t *scroll = lv_obj_create(c);
    lv_obj_remove_style_all(scroll);
    lv_obj_set_size(scroll, lv_pct(100), lv_pct(100));
    lv_obj_set_scroll_dir(scroll, LV_DIR_VER);
    lv_obj_set_flex_flow(scroll, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(scroll, UBO_SCALE(3), 0);

    for (int i = 0; i < rows; i++) {
        char name[64];
        char val[32];
        char unit[16];
        nth_line(labels, i, name, sizeof(name));
        nth_line(values, i, val, sizeof(val));
        nth_line(units, i, unit, sizeof(unit));

        lv_obj_t *row = lv_obj_create(scroll);
        lv_obj_remove_style_all(row);
        lv_obj_set_width(row, lv_pct(100));
        lv_obj_set_height(row, LV_SIZE_CONTENT);
        lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
        lv_obj_set_flex_align(row, LV_FLEX_ALIGN_SPACE_BETWEEN,
                              LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);

        /* The name gets the larger share and the reading is right-aligned
         * against the edge, so the numbers line up down the column. */
        lv_obj_t *n = lv_label_create(row);
        lv_label_set_long_mode(n, LV_LABEL_LONG_DOT);
        lv_obj_set_width(n, lv_pct(55));
        lv_obj_set_style_text_font(n, UBO_FONT_SM, 0);
        lv_obj_set_style_text_color(n, UBO_COL_MUTED, 0);
        lv_label_set_text(n, name);

        lv_obj_t *r = lv_label_create(row);
        lv_label_set_long_mode(r, LV_LABEL_LONG_DOT);
        lv_obj_set_width(r, lv_pct(43));
        lv_obj_set_style_text_align(r, LV_TEXT_ALIGN_RIGHT, 0);
        lv_obj_set_style_text_font(r, UBO_FONT_SM, 0);
        lv_obj_set_style_text_color(r, UBO_COL_FG, 0);
        char reading[52];
        snprintf(reading, sizeof(reading), "%s%s%s", val[0] ? val : "-",
                 unit[0] ? " " : "", unit);
        lv_label_set_text(r, reading);
    }

    /* More entities than fit the panel (a BME680 has five) scroll with UP/DOWN,
     * reusing the text viewer's scroll path. */
    s_rw_kind = RW_TEXT;
    s_text_scroll = scroll;
}

/* image_viewer / frame_stream: a centred lv_image fed by ubo_render_update_frame
 * (one-shot for image_viewer, repeatedly for frame_stream). */
static lv_image_dsc_t s_frame_dsc;
static uint16_t *s_frame_buf;

static void attach_chunk_frame(lv_obj_t *img);

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
    lv_obj_set_style_text_font(s_frame_hint, UBO_FONT_SM, 0);
    lv_label_set_text(s_frame_hint, stream ? "Waiting for video..." : "");

    /* A still image is pan/zoomable (UP/DOWN + L1/L2/L3); a live stream is not. */
    if (!stream) {
        s_rw_kind = RW_IMAGE;
        s_img_obj = img;
        s_img_mode = 0;
        /* The pixels usually beat this view here (see ubo_render_update_frame_
         * chunk), and a still has no next frame to try again with -- so show
         * whatever is already assembled. A live stream skips this: its next
         * frame is 100ms away and a stale one would flash first. */
        if (s_chunk_ready && s_frame_buf) {
            attach_chunk_frame(img);
            lv_obj_add_flag(s_frame_hint, LV_OBJ_FLAG_HIDDEN);
        }
    }
}

/* Panels are <=1000px; anything larger is a corrupt/hostile size field. */
#define FRAME_MAX_DIM 4096

void ubo_render_update_frame(const uint8_t *rgb, size_t rgb_len, int32_t w,
                             int32_t h)
{
    lv_obj_t *img = ubo_screen_frame_target();
    if (!img || !rgb || w <= 0 || h <= 0 || w > FRAME_MAX_DIM ||
        h > FRAME_MAX_DIM) {
        return;
    }
    const size_t n = (size_t)w * (size_t)h;
    if (rgb_len < n * 3) {
        return; /* wire-claimed dimensions exceed the actual payload */
    }
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
    s_img_fit = scale;   /* zoom-out floor for the still-image viewer */
    s_img_scale = scale;
    s_chunk_w = 0; /* force the chunked path to reconfigure if it takes over */
    s_chunk_h = 0;
    s_chunk_next_row = 0;
    s_chunk_ready = false; /* s_frame_buf now holds full-res data, not chunks */
    s_chunk_attached = false;

    if (s_frame_hint) {
        lv_obj_add_flag(s_frame_hint, LV_OBJ_FLAG_HIDDEN);
    }
}

/* Point the live image object at the assembled frame and size it to the panel.
 * Split out because it runs from two places: the chunk that completes a frame,
 * and `build_frame_view` when the view for an already-assembled still appears. */
static void attach_chunk_frame(lv_obj_t *img)
{
    const size_t n = (size_t)s_chunk_w * (size_t)s_chunk_h;
    memset(&s_frame_dsc, 0, sizeof(s_frame_dsc));
    s_frame_dsc.header.cf = LV_COLOR_FORMAT_RGB565;
    s_frame_dsc.header.w = (uint32_t)s_chunk_w;
    s_frame_dsc.header.h = (uint32_t)s_chunk_h;
    s_frame_dsc.header.stride = (uint32_t)s_chunk_w * 2;
    s_frame_dsc.data = (const uint8_t *)s_frame_buf;
    s_frame_dsc.data_size = (uint32_t)(n * 2);
    lv_image_set_src(img, &s_frame_dsc);

    /* Unlike the full-res path, low-res stream frames upscale to fill the
     * panel (nearest-neighbor: antialiased transforms are too slow on the
     * ESP32 and a viewfinder wants crisp pixels over smoothing). */
    int32_t sx = (int32_t)((long)UBO_W * 256 / s_chunk_w);
    int32_t sy = (int32_t)((long)UBO_H * 256 / s_chunk_h);
    int32_t scale = sx < sy ? sx : sy;
    if (scale > 1024) {
        scale = 1024; /* cap the upscale at 4x */
    }
    lv_image_set_antialias(img, false);
    lv_image_set_scale(img, (uint32_t)scale);
    lv_obj_center(img);
    /* image_viewer is pan/zoomable and now reaches MCU clients through this
     * path (its picture used to come inline in props), so the still viewer's
     * zoom floor has to be seeded here too, not only in
     * ubo_render_update_frame. Unused when the view is a live stream. */
    s_img_fit = scale;
    s_img_scale = scale;
    s_chunk_attached = true;
}

void ubo_render_update_frame_chunk(const uint8_t *rgb565, size_t len,
                                   int32_t row_offset, int32_t w, int32_t h)
{
    /* Deliberately assembled even when there is no image object yet: the
     * chunks ride the event stream while the view that displays them arrives
     * on the store stream, and the event stream regularly wins by ~70ms. The
     * pixels are kept and `build_frame_view` attaches them when the view shows
     * up -- for a still, dropping them here means dropping them forever. */
    lv_obj_t *img = ubo_screen_frame_target();
    if (!rgb565 || w <= 0 || h <= 0 || w > FRAME_MAX_DIM ||
        h > FRAME_MAX_DIM || row_offset < 0) {
        return;
    }
    const size_t row_bytes = (size_t)w * 2;
    if (len == 0 || len % row_bytes != 0) {
        return;
    }
    const int32_t rows = (int32_t)(len / row_bytes);
    if (row_offset + rows > h) {
        return;
    }

    /* Only assemble a sequence that starts at row 0 and stays contiguous. A
     * camera survives a lost chunk because the next frame repaints everything
     * 100ms later; a STILL has no next frame, so a gap would be displayed as a
     * permanent black band. Waiting for a clean sequence shows the previous
     * content (or the hint) instead of a half-painted picture. */
    if (row_offset != s_chunk_next_row) {
        if (row_offset != 0) {
            return;
        }
        s_chunk_next_row = 0;
    }

    if (w != s_chunk_w || h != s_chunk_h) {
        const size_t n = (size_t)w * (size_t)h;
        uint16_t *buf = realloc(s_frame_buf, n * 2);
        if (!buf) {
            return; /* keep prior state; drop the chunk */
        }
        s_frame_buf = buf;
        memset(s_frame_buf, 0, n * 2);
        s_chunk_w = w;
        s_chunk_h = h;
        s_chunk_ready = false;
        s_chunk_attached = false;
    }

    memcpy(&s_frame_buf[(size_t)row_offset * (size_t)w], rgb565, len);
    s_chunk_next_row = row_offset + rows;

    if (s_chunk_next_row == h) {
        s_chunk_next_row = 0; /* ready for the next frame */
        s_chunk_ready = true;
        if (!img) {
            return; /* held until the view that shows it is built */
        }
        if (!s_chunk_attached) {
            attach_chunk_frame(img);
        }
        if (s_frame_hint) {
            lv_obj_add_flag(s_frame_hint, LV_OBJ_FLAG_HIDDEN);
        }
        lv_obj_invalidate(img); /* repaint once per completed frame */
    }
}

static void build_placeholder(const char *kind)
{
    lv_obj_t *c = column(ubo_screen_content());
    lv_obj_t *l = lv_label_create(c);
    lv_obj_set_style_text_align(l, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_text_color(l, UBO_COL_MUTED, 0);
    lv_obj_set_style_text_font(l, UBO_FONT_MD, 0);
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
                 ubo_render_prop_get(v, "label"),
                 ubo_render_prop_get(v, "caption"));
    } else if (strcmp(kind, "qr_code_carousel") == 0) {
        build_qr_carousel(v);
    } else if (strcmp(kind, "readings") == 0) {
        build_readings(v);
    } else if (strcmp(kind, "image_viewer") == 0) {
        build_frame_view(false);
    } else if (strcmp(kind, "frame_stream") == 0) {
        build_frame_view(true);
    } else {
        build_placeholder(kind);
    }

    ubo_status_bar_reapply();
}

static void image_scroll(bool up)
{
    if (!s_img_obj) {
        return;
    }
    if (s_img_mode == 2) { /* zoom */
        int32_t s = s_img_scale + (up ? 26 : -26); /* ~10% per step */
        if (s < s_img_fit) {
            s = s_img_fit;
        }
        if (s > 1024) {
            s = 1024; /* cap at 4x */
        }
        s_img_scale = s;
        lv_image_set_scale(s_img_obj, (uint16_t)s);
        lv_obj_center(s_img_obj);
    } else { /* pan vertically (mode 0) or horizontally (mode 1) */
        const int step = up ? 24 : -24;
        if (s_img_mode == 0) {
            lv_obj_set_y(s_img_obj, lv_obj_get_y(s_img_obj) + step);
        } else {
            lv_obj_set_x(s_img_obj, lv_obj_get_x(s_img_obj) + step);
        }
    }
}

void ubo_render_scroll(const char *direction)
{
    if (!direction) {
        return;
    }
    const bool up = strcmp(direction, "up") == 0;
    switch (s_rw_kind) {
        case RW_TEXT:
            if (s_text_scroll) {
                lv_obj_scroll_by(s_text_scroll, 0, up ? 100 : -100, LV_ANIM_ON);
            }
            break;
        case RW_CAROUSEL:
            if (s_car_total > 1) {
                s_car_index =
                    (s_car_index + (up ? -1 : 1) + s_car_total) % s_car_total;
                carousel_render();
            }
            break;
        case RW_IMAGE:
            image_scroll(up);
            break;
        default:
            break;
    }
}

void ubo_render_choose(int index)
{
    /* Image viewer: L1/L2/L3 switch pan-vertical / pan-horizontal / zoom mode. */
    if (s_rw_kind == RW_IMAGE && index >= 0 && index <= 2) {
        s_img_mode = index;
    }
}
