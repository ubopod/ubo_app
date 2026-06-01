/**
 * @file view_notification.c
 * Notification view: an accent icon, title (header), wrapped content, and
 * optional action hints.
 */
#include "ubo_views.h"

void ubo_build_notification(const ubo_notification_view *v)
{
    ubo_screen_show_chrome(v->show_status_bar, v->show_status_bar);
    ubo_screen_set_title((v->title && v->title[0]) ? v->title : "Notification");

    ubo_screen_clear_content();
    lv_obj_t *c = ubo_screen_content();
    lv_obj_set_flex_flow(c, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(c, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_all(c, 8, 0);
    lv_obj_set_style_pad_row(c, 8, 0);

    const lv_color_t accent = ubo_parse_color(v->color, UBO_COL_INFO);

    if (v->icon && v->icon[0]) {
        lv_obj_t *ic = lv_label_create(c);
        lv_obj_set_style_text_font(ic, ubo_font_icon_18(), 0);
        lv_obj_set_style_text_color(ic, accent, 0);
        lv_label_set_text(ic, v->icon);
    }

    if (v->content && v->content[0]) {
        lv_obj_t *txt = lv_label_create(c);
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
