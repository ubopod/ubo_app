/**
 * @file view_prompt.c
 * Prompt view: a wrapped prompt message plus up to two option "buttons".
 */
#include "ubo_views.h"

void ubo_build_prompt(const ubo_prompt_view *v)
{
    ubo_screen_show_chrome(v->show_status_bar, v->show_status_bar);
    ubo_screen_set_title((v->title && v->title[0]) ? v->title : "");

    ubo_screen_clear_content();
    lv_obj_t *c = ubo_screen_content();
    lv_obj_set_flex_flow(c, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(c, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_all(c, 8, 0);
    lv_obj_set_style_pad_row(c, 8, 0);

    if (v->prompt && v->prompt[0]) {
        lv_obj_t *msg = lv_label_create(c);
        lv_label_set_long_mode(msg, LV_LABEL_LONG_WRAP);
        lv_obj_set_width(msg, lv_pct(100));
        lv_obj_set_style_text_align(msg, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_set_style_text_color(msg, UBO_COL_FG, 0);
        lv_obj_set_style_text_font(msg, &lv_font_montserrat_16, 0);
        lv_label_set_text(msg, v->prompt);
    }

    const lv_color_t opt_colors[2] = {UBO_COL_INFO, UBO_COL_SUCCESS};
    const int n = v->item_count < 2 ? v->item_count : 2;
    for (int i = 0; i < n; i++) {
        lv_obj_t *btn = lv_obj_create(c);
        lv_obj_remove_style_all(btn);
        lv_obj_set_width(btn, lv_pct(90));
        lv_obj_set_height(btn, 32);
        lv_obj_set_style_radius(btn, 6, 0);
        lv_obj_set_style_bg_color(btn, opt_colors[i], 0);
        lv_obj_set_style_bg_opa(btn, LV_OPA_COVER, 0);
        lv_obj_clear_flag(btn, LV_OBJ_FLAG_SCROLLABLE);

        lv_obj_t *lbl = lv_label_create(btn);
        lv_obj_set_style_text_color(lbl, lv_color_black(), 0);
        lv_obj_set_style_text_font(lbl, &lv_font_montserrat_16, 0);
        lv_label_set_text(lbl, v->items[i].label ? v->items[i].label : "");
        lv_obj_center(lbl);
    }

    ubo_status_bar_reapply();
}
