/**
 * @file view_prompt.c
 * Prompt view: an icon + message, then up to two option bars.
 *
 * ubo_gui maps the first option to L2 and the second to L3 (L1 is unused), so we
 * lay the page out as the three band slots: L1 = icon + prompt text, L2 = first
 * option, L3 = second option — consistent with the menu/notification item
 * alignment. Options are rendered as item bars so they pick up any colours the
 * core sets (e.g. a destructive action).
 */
#include "ubo_views.h"

void ubo_build_prompt(const ubo_prompt_view *v)
{
    ubo_screen_show_chrome(v->show_status_bar, v->show_status_bar);
    ubo_screen_set_title((v->title && v->title[0]) ? v->title : "");

    ubo_screen_clear_content();
    lv_obj_t *page = ubo_screen_content();

    const int n = v->item_count < 2 ? v->item_count : 2;

    /* Three band slots, top-anchored at the header: L1 (icon + message),
     * L2 (first option), L3 (second option). */
    lv_obj_t *col = lv_obj_create(page);
    lv_obj_remove_style_all(col);
    lv_obj_clear_flag(col, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_width(col, UBO_W - 6);
    lv_obj_set_height(col, LV_SIZE_CONTENT);
    lv_obj_set_pos(col, 0, UBO_HEADER_H);
    lv_obj_set_flex_flow(col, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(col, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_row(col, UBO_ITEM_GAP, 0);

    /* L1 slot: icon over the prompt message. */
    lv_obj_t *head = lv_obj_create(col);
    lv_obj_remove_style_all(head);
    lv_obj_clear_flag(head, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_size(head, lv_pct(100), UBO_ITEM_H);
    lv_obj_set_flex_flow(head, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(head, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER);
    if (v->icon && v->icon[0]) {
        lv_obj_t *ic = lv_label_create(head);
        lv_obj_set_style_text_font(ic, UBO_FONT_ICON, 0);
        lv_obj_set_style_text_color(ic, UBO_COL_FG, 0);
        lv_label_set_text(ic, v->icon);
    }
    if (v->prompt && v->prompt[0]) {
        lv_obj_t *msg = lv_label_create(head);
        lv_label_set_long_mode(msg, LV_LABEL_LONG_WRAP);
        lv_obj_set_width(msg, lv_pct(100));
        lv_obj_set_style_text_align(msg, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_set_style_text_color(msg, UBO_COL_FG, 0);
        lv_obj_set_style_text_font(msg, UBO_FONT_SM, 0);
        lv_label_set_text(msg, v->prompt);
    }

    /* L2 / L3 slots: the option bars (first -> L2, second -> L3). */
    for (int i = 0; i < n; i++) {
        ubo_item_bar(col, &v->items[i], false);
    }

    ubo_status_bar_reapply();
}
