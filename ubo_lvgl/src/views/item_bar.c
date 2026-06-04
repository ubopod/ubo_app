/**
 * @file item_bar.c
 * Shared menu-item "bar" widget, matching ubo_gui's ItemWidget: a bar (height
 * 52, gap 7) rounded on the right end and squared on the left (the side touching
 * the screen edge), with a leading icon and a label. Used by the menu view (full
 * width) and the home view's left strip (short, icon-only).
 */
#include "ubo_views.h"

lv_obj_t *ubo_item_bar(lv_obj_t *parent, const ubo_menu_item *it, bool short_mode)
{
    const int pad_left = short_mode ? 0 : 10;

    lv_obj_t *row = lv_obj_create(parent);
    lv_obj_remove_style_all(row);
    lv_obj_set_height(row, UBO_ITEM_H);
    lv_obj_set_width(row, short_mode ? UBO_SHORT_W : lv_pct(100));
    lv_obj_set_style_radius(row, UBO_ITEM_RADIUS, 0);
    lv_obj_clear_flag(row, LV_OBJ_FLAG_SCROLLABLE);

    const lv_color_t bg = ubo_parse_color(
        it->background_color,
        it->is_selected ? UBO_COL_SELECT : lv_color_hex(0x202020));
    lv_obj_set_style_bg_color(row, bg, 0);
    lv_obj_set_style_bg_opa(row, LV_OPA_COVER, 0);
    if (it->is_selected) {
        lv_obj_set_style_border_color(row, UBO_COL_INFO, 0);
        lv_obj_set_style_border_width(row, 2, 0);
    }

    const lv_color_t fg = ubo_parse_color(it->color, UBO_COL_FG);
    lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
    if (short_mode) {
        lv_obj_set_flex_align(row, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER,
                              LV_FLEX_ALIGN_CENTER);
    } else {
        lv_obj_set_flex_align(row, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER,
                              LV_FLEX_ALIGN_CENTER);
        lv_obj_set_style_pad_left(row, pad_left, 0);
        lv_obj_set_style_pad_column(row, 8, 0);
    }

    /* Square the LEFT corners: overlay a same-colour rect over them. lv_obj_align
     * is relative to the content area, so offset by -pad_left to reach the true
     * left edge (otherwise the rounded corner peeks out past the padding). Added
     * before the icon/label so they draw on top. */
    lv_obj_t *left_fill = lv_obj_create(row);
    lv_obj_remove_style_all(left_fill);
    lv_obj_add_flag(left_fill, LV_OBJ_FLAG_IGNORE_LAYOUT);
    lv_obj_clear_flag(left_fill, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_size(left_fill, UBO_ITEM_RADIUS, lv_pct(100));
    lv_obj_align(left_fill, LV_ALIGN_LEFT_MID, -pad_left, 0);
    lv_obj_set_style_bg_color(left_fill, bg, 0);
    lv_obj_set_style_bg_opa(left_fill, LV_OPA_COVER, 0);

    if (it->icon && it->icon[0]) {
        lv_obj_t *ic = lv_label_create(row);
        lv_obj_set_style_text_font(ic, UBO_FONT_ICON, 0);
        lv_obj_set_style_text_color(ic, fg, 0);
        lv_label_set_text(ic, it->icon);
    }

    if (!short_mode) {
        lv_obj_t *lbl = lv_label_create(row);
        lv_obj_set_style_text_color(lbl, fg, 0);
        lv_obj_set_style_text_font(lbl, UBO_FONT_LG, 0);
        lv_label_set_long_mode(lbl, LV_LABEL_LONG_DOT);
        lv_obj_set_flex_grow(lbl, 1);
        lv_label_set_text(lbl, it->label ? it->label : "");
    }

    /* Register for touch hit-testing so taps only select where items are drawn. */
    ubo_hit_register(row);
    return row;
}
