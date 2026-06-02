/**
 * @file view_notification.c
 * Notification view. Matches ubo_gui's notification_widget.kv 3-column layout:
 *   - left  : up to 3 action items as icon-only "short" bars (mapped to L1/L2/L3)
 *   - center: accent icon, title, and wrapped content
 *   - right : the page/scroll slider
 * (The previous build centred only the icon + content, dropping the title and
 * the action items entirely.)
 */
#include "ubo_views.h"

void ubo_build_notification(const ubo_notification_view *v)
{
    ubo_screen_show_chrome(v->show_status_bar, v->show_status_bar);
    ubo_screen_set_title((v->title && v->title[0]) ? v->title : "Notification");

    ubo_screen_clear_content();
    lv_obj_t *page = ubo_screen_content();

    const lv_color_t accent = ubo_parse_color(v->color, UBO_COL_INFO);
    const int n = v->item_count < 3 ? v->item_count : 3;
    const bool scrollable = v->total_pages > 1;

    /* Full-screen horizontal row: [items] [icon/title/content] [slider gap]. */
    lv_obj_t *row = lv_obj_create(page);
    lv_obj_remove_style_all(row);
    lv_obj_clear_flag(row, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_size(row, UBO_W - (scrollable ? 12 : 0), UBO_H);
    lv_obj_set_pos(row, 0, 0);
    lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(row, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER);

    /* Left: the action items as icon-only short bars (L1/L2/L3 top to bottom). */
    if (n > 0) {
        lv_obj_t *left = lv_obj_create(row);
        lv_obj_remove_style_all(left);
        lv_obj_clear_flag(left, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_set_width(left, UBO_SHORT_W);
        lv_obj_set_height(left, LV_SIZE_CONTENT);
        lv_obj_set_flex_flow(left, LV_FLEX_FLOW_COLUMN);
        lv_obj_set_flex_align(left, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER,
                              LV_FLEX_ALIGN_CENTER);
        lv_obj_set_style_pad_row(left, UBO_ITEM_GAP, 0);
        for (int i = 0; i < n; i++) {
            ubo_item_bar(left, &v->items[i], true);
        }
    }

    /* Center: accent icon, title, content — vertically centred, wraps. */
    lv_obj_t *center = lv_obj_create(row);
    lv_obj_remove_style_all(center);
    lv_obj_clear_flag(center, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_flex_grow(center, 1);
    lv_obj_set_height(center, lv_pct(100));
    lv_obj_set_flex_flow(center, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(center, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_all(center, 4, 0);
    lv_obj_set_style_pad_row(center, 5, 0);

    if (v->icon && v->icon[0]) {
        lv_obj_t *ic = lv_label_create(center);
        lv_obj_set_style_text_font(ic, ubo_font_icon_18(), 0);
        lv_obj_set_style_text_color(ic, accent, 0);
        lv_label_set_text(ic, v->icon);
    }
    if (v->title && v->title[0]) {
        lv_obj_t *t = lv_label_create(center);
        lv_label_set_long_mode(t, LV_LABEL_LONG_WRAP);
        lv_obj_set_width(t, lv_pct(100));
        lv_obj_set_style_text_align(t, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_set_style_text_color(t, UBO_COL_FG, 0);
        lv_obj_set_style_text_font(t, &lv_font_montserrat_18, 0);
        lv_label_set_text(t, v->title);
    }
    if (v->content && v->content[0]) {
        lv_obj_t *txt = lv_label_create(center);
        lv_label_set_long_mode(txt, LV_LABEL_LONG_WRAP);
        lv_obj_set_width(txt, lv_pct(100));
        lv_obj_set_style_text_align(txt, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_set_style_text_color(txt, UBO_COL_FG, 0);
        lv_obj_set_style_text_font(txt, &lv_font_montserrat_16, 0);
        lv_label_set_text(txt, v->content);
    }

    ubo_screen_set_page_slider(v->page_index, v->total_pages);
    ubo_status_bar_reapply();
}
