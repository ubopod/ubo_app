/**
 * @file view_chat.c
 * Chat overlay view (ChatViewData): a vertically scrollable conversation of
 * speech bubbles, newest at the bottom. Assistant bubbles align left, user
 * bubbles align right; each carries its own fill/foreground colors precomputed
 * by the core. Audio bubbles (kind=="audio") draw their normalized waveform as
 * a row of bars instead of text.
 */
#include <string.h>

#include "ubo_views.h"

/* Max bubble width as a fraction of the panel, so bubbles never span edge-to-
 * edge and the left/right alignment stays legible. */
#define CHAT_BUBBLE_PCT 78
#define CHAT_WAVE_MAX_BARS 24

static void build_waveform(lv_obj_t *bubble, const ubo_chat_bubble *b)
{
    lv_color_t fg = ubo_parse_color(b->color, UBO_COL_FG);
    lv_obj_t *wave = lv_obj_create(bubble);
    lv_obj_remove_style_all(wave);
    lv_obj_set_height(wave, UBO_SCALE(28));
    lv_obj_set_width(wave, LV_SIZE_CONTENT);
    lv_obj_clear_flag(wave, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_flex_flow(wave, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(wave, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(wave, UBO_SCALE(1) > 0 ? UBO_SCALE(1) : 1, 0);

    int n = b->waveform_count > CHAT_WAVE_MAX_BARS ? CHAT_WAVE_MAX_BARS
                                                   : b->waveform_count;
    for (int i = 0; i < n; i++) {
        float v = b->waveform[i];
        if (v < 0.0f) {
            v = 0.0f;
        } else if (v > 1.0f) {
            v = 1.0f;
        }
        int h = UBO_SCALE(3) + (int)(v * UBO_SCALE(22));
        lv_obj_t *bar = lv_obj_create(wave);
        lv_obj_remove_style_all(bar);
        lv_obj_set_size(bar, UBO_SCALE(2) > 0 ? UBO_SCALE(2) : 2, h);
        lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, 0);
        lv_obj_set_style_bg_color(bar, fg, 0);
        lv_obj_set_style_radius(bar, UBO_SCALE(1), 0);
    }
}

void ubo_build_chat(const ubo_chat_view *v)
{
    ubo_screen_show_chrome(v->show_status_bar, false);
    if (v->show_status_bar) {
        ubo_screen_set_title(ubo_status_bar_title());
    }

    ubo_screen_clear_content();
    ubo_hit_clear();
    lv_obj_t *page = ubo_screen_content();

    const int top = v->show_status_bar ? UBO_HEADER_H : 0;
    const int max_w = (UBO_W * CHAT_BUBBLE_PCT) / 100;

    /* Scrollable column; main-axis END keeps the newest bubble pinned to the
     * bottom (and pads short conversations down) like a chat transcript. */
    lv_obj_t *col = lv_obj_create(page);
    lv_obj_remove_style_all(col);
    lv_obj_set_size(col, UBO_W, UBO_H - top);
    lv_obj_set_pos(col, 0, top);
    lv_obj_set_flex_flow(col, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(col, LV_FLEX_ALIGN_END, LV_FLEX_ALIGN_START,
                          LV_FLEX_ALIGN_START);
    lv_obj_set_style_pad_all(col, UBO_SCALE(6), 0);
    lv_obj_set_style_pad_row(col, UBO_SCALE(5), 0);
    lv_obj_set_scroll_dir(col, LV_DIR_VER);
    lv_obj_set_scrollbar_mode(col, LV_SCROLLBAR_MODE_OFF);

    if (v->bubble_count == 0) {
        lv_obj_t *empty = lv_label_create(col);
        lv_label_set_text(empty, "No messages yet");
        lv_obj_set_style_text_color(empty, UBO_COL_MUTED, 0);
        lv_obj_set_style_text_font(empty, UBO_FONT_SM, 0);
        return;
    }

    for (int i = 0; i < v->bubble_count; i++) {
        const ubo_chat_bubble *b = &v->bubbles[i];
        bool right = b->alignment && strcmp(b->alignment, "right") == 0;

        /* Full-width row that aligns its single bubble child left or right. */
        lv_obj_t *row = lv_obj_create(col);
        lv_obj_remove_style_all(row);
        lv_obj_set_width(row, lv_pct(100));
        lv_obj_set_height(row, LV_SIZE_CONTENT);
        lv_obj_clear_flag(row, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
        lv_obj_set_flex_align(row,
                              right ? LV_FLEX_ALIGN_END : LV_FLEX_ALIGN_START,
                              LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);

        lv_obj_t *bubble = lv_obj_create(row);
        lv_obj_remove_style_all(bubble);
        lv_obj_set_width(bubble, LV_SIZE_CONTENT);
        lv_obj_set_style_max_width(bubble, max_w, 0);
        lv_obj_set_height(bubble, LV_SIZE_CONTENT);
        lv_obj_clear_flag(bubble, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_set_style_bg_opa(bubble, LV_OPA_COVER, 0);
        lv_obj_set_style_bg_color(
            bubble, ubo_parse_color(b->background_color, UBO_COL_SELECT), 0);
        lv_obj_set_style_radius(bubble, UBO_SCALE(10), 0);
        lv_obj_set_style_pad_hor(bubble, UBO_SCALE(8), 0);
        lv_obj_set_style_pad_ver(bubble, UBO_SCALE(5), 0);
        /* A bubble bound to a hardware button gets a thin accent border. */
        if (b->pointer_key && b->pointer_key[0]) {
            lv_obj_set_style_border_width(bubble, UBO_SCALE(2), 0);
            lv_obj_set_style_border_color(
                bubble, ubo_parse_color(b->color, UBO_COL_INFO), 0);
            lv_obj_set_style_border_opa(bubble, LV_OPA_80, 0);
        }

        if (b->kind && strcmp(b->kind, "audio") == 0 && b->waveform_count > 0) {
            build_waveform(bubble, b);
        } else {
            lv_obj_t *lbl = lv_label_create(bubble);
            lv_label_set_text(lbl, b->text ? b->text : "");
            lv_label_set_long_mode(lbl, LV_LABEL_LONG_WRAP);
            lv_obj_set_width(lbl, LV_SIZE_CONTENT);
            lv_obj_set_style_max_width(lbl, max_w - UBO_SCALE(16), 0);
            lv_obj_set_style_text_color(lbl, ubo_parse_color(b->color,
                                                             UBO_COL_FG),
                                        0);
            lv_obj_set_style_text_font(lbl, UBO_FONT_SM, 0);
        }
    }

    /* Land on the newest message. */
    lv_obj_update_layout(col);
    lv_obj_scroll_to_y(col, LV_COORD_MAX, LV_ANIM_OFF);
}
