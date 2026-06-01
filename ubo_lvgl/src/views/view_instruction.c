/**
 * @file view_instruction.c
 * Instruction view: an optional spinner plus instruction / progress / footer
 * text. Used for "please wait" style screens.
 */
#include "ubo_views.h"

static lv_obj_t *centered_label(lv_obj_t *parent, const char *text,
                                const lv_font_t *font, lv_color_t color)
{
    lv_obj_t *l = lv_label_create(parent);
    lv_label_set_long_mode(l, LV_LABEL_LONG_WRAP);
    lv_obj_set_width(l, lv_pct(100));
    lv_obj_set_style_text_align(l, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_text_font(l, font, 0);
    lv_obj_set_style_text_color(l, color, 0);
    lv_label_set_text(l, text);
    return l;
}

void ubo_build_instruction(const ubo_instruction_view *v)
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

    if (v->spinner) {
        lv_obj_t *sp = lv_spinner_create(c);
        lv_obj_set_size(sp, 44, 44);
        lv_obj_set_style_arc_color(sp, lv_color_hex(0x303030), LV_PART_MAIN);
        lv_obj_set_style_arc_color(sp, UBO_COL_INFO, LV_PART_INDICATOR);
        lv_obj_set_style_arc_width(sp, 5, LV_PART_MAIN);
        lv_obj_set_style_arc_width(sp, 5, LV_PART_INDICATOR);
    }

    if (v->instruction && v->instruction[0]) {
        centered_label(c, v->instruction, &lv_font_montserrat_16, UBO_COL_FG);
    }
    if (v->progress_text && v->progress_text[0]) {
        centered_label(c, v->progress_text, &lv_font_montserrat_14,
                       UBO_COL_INFO);
    }
    if (v->footer_text && v->footer_text[0]) {
        centered_label(c, v->footer_text, &lv_font_montserrat_12, UBO_COL_MUTED);
    }

    ubo_status_bar_reapply();
}
