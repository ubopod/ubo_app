/**
 * @file view_home.c
 * Home view, arranged like ubo_gui's HomePage: a left strip of icon-only menu
 * item bars (the nav entries), CPU/RAM arc gauges stacked in the centre, and a
 * vertical volume bar on the right.
 */
#include "ubo_views.h"

static lv_obj_t *plain_col(lv_obj_t *parent, int32_t width)
{
    lv_obj_t *o = lv_obj_create(parent);
    lv_obj_remove_style_all(o);
    if (width > 0) {
        lv_obj_set_width(o, width);
    } else {
        lv_obj_set_flex_grow(o, 1);
    }
    lv_obj_set_height(o, lv_pct(100));
    lv_obj_clear_flag(o, LV_OBJ_FLAG_SCROLLABLE);
    return o;
}

static void make_gauge(lv_obj_t *parent, const char *caption, lv_color_t col,
                       double value)
{
    /* Larger arc than the original 58px reference, responsive. The wrap height
     * is bounded so two gauges fit the content band (binding case: the 240
     * panel, content 170 => wrap <= 85). */
    const int arc_sz = UBO_SCALE(64);
    const int arc_w = UBO_SCALE(8);

    lv_obj_t *wrap = lv_obj_create(parent);
    lv_obj_remove_style_all(wrap);
    lv_obj_set_size(wrap, lv_pct(100), UBO_SCALE(82));
    lv_obj_clear_flag(wrap, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t *arc = lv_arc_create(wrap);
    lv_obj_set_size(arc, arc_sz, arc_sz);
    lv_obj_align(arc, LV_ALIGN_TOP_MID, 0, 0);
    lv_arc_set_rotation(arc, 135);
    lv_arc_set_bg_angles(arc, 0, 270);
    lv_arc_set_range(arc, 0, 100);
    lv_arc_set_value(arc, (int)value);
    lv_obj_remove_style(arc, NULL, LV_PART_KNOB);
    lv_obj_clear_flag(arc, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_style_arc_color(arc, lv_color_hex(0x303030), LV_PART_MAIN);
    lv_obj_set_style_arc_width(arc, arc_w, LV_PART_MAIN);
    lv_obj_set_style_arc_color(arc, col, LV_PART_INDICATOR);
    lv_obj_set_style_arc_width(arc, arc_w, LV_PART_INDICATOR);

    lv_obj_t *val_lbl = lv_label_create(arc);
    lv_label_set_text_fmt(val_lbl, "%d", (int)value);
    lv_obj_set_style_text_color(val_lbl, UBO_COL_FG, 0);
    lv_obj_set_style_text_font(val_lbl, UBO_FONT_LG, 0);
    lv_obj_center(val_lbl);

    lv_obj_t *cap = lv_label_create(wrap);
    lv_label_set_text(cap, caption);
    lv_obj_set_style_text_color(cap, UBO_COL_MUTED, 0);
    lv_obj_set_style_text_font(cap, UBO_FONT_XS, 0);
    lv_obj_align(cap, LV_ALIGN_BOTTOM_MID, 0, 0);
}

void ubo_build_home(const ubo_home_view *v)
{
    ubo_screen_show_chrome(v->show_status_bar, v->show_status_bar);
    ubo_screen_set_title(ubo_status_bar_title());

    ubo_screen_clear_content();
    /* Confine the home content to the band so the gauges/volume don't bleed into
     * the header/footer. */
    lv_obj_t *c = ubo_screen_band_box();
    lv_obj_set_flex_flow(c, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(c, LV_FLEX_ALIGN_SPACE_BETWEEN, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_all(c, 0, 0);

    /* Left: icon-only nav item bars, vertically centered. */
    lv_obj_t *left = plain_col(c, UBO_SHORT_W);
    lv_obj_set_flex_flow(left, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(left, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_row(left, UBO_ITEM_GAP, 0);
    int n = v->item_count < UBO_PAGE_SIZE ? v->item_count : UBO_PAGE_SIZE;
    for (int i = 0; i < n; i++) {
        ubo_item_bar(left, &v->items[i], true);
    }

    /* Centre: CPU above RAM. */
    lv_obj_t *center = plain_col(c, 0);
    lv_obj_set_flex_flow(center, LV_FLEX_FLOW_COLUMN);
    /* SPACE_EVENLY spreads CPU/RAM apart with even margins. */
    lv_obj_set_flex_align(center, LV_FLEX_ALIGN_SPACE_EVENLY, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER);
    make_gauge(center, "CPU", UBO_COL_CPU, v->cpu_percent);
    make_gauge(center, "RAM", UBO_COL_RAM, v->ram_percent);

    /* Right: vertical volume bar (ubo_gui VolumeWidget colours) with a
     * volume-high glyph at the top and a volume-low glyph at the bottom. */
    lv_obj_t *right = plain_col(c, UBO_SHORT_W);

    lv_obj_t *vol = lv_bar_create(right);
    /* ~25% wider than the original 25px reference, responsive. */
    lv_obj_set_size(vol, UBO_SCALE(31), lv_pct(100));
    lv_obj_center(vol);
    lv_bar_set_range(vol, 0, 100);
    lv_bar_set_value(vol, (int)(v->volume_level * 100), LV_ANIM_OFF);
    lv_obj_set_style_radius(vol, UBO_SCALE(6), LV_PART_MAIN);
    lv_obj_set_style_radius(vol, UBO_SCALE(6), LV_PART_INDICATOR);
    lv_obj_set_style_bg_color(vol, lv_color_hex(0x363F4B), LV_PART_MAIN);
    lv_obj_set_style_bg_opa(vol, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_set_style_bg_color(vol, lv_color_hex(0x68B7FF), LV_PART_INDICATOR);
    ubo_hit_set_volume(vol); /* enable touch slide/tap volume control */

    lv_obj_t *v_top = lv_label_create(right);
    lv_obj_set_style_text_font(v_top, UBO_FONT_ICON, 0);
    lv_obj_set_style_text_color(v_top, UBO_COL_FG, 0);
    lv_label_set_text(v_top, "\U000f057e"); /* volume-high */
    lv_obj_align(v_top, LV_ALIGN_TOP_MID, 0, 2);

    lv_obj_t *v_bot = lv_label_create(right);
    lv_obj_set_style_text_font(v_bot, UBO_FONT_ICON, 0);
    lv_obj_set_style_text_color(v_bot, UBO_COL_FG, 0);
    lv_label_set_text(v_bot, "\U000f0580"); /* speaker with one line (volume-low) */
    lv_obj_align(v_bot, LV_ALIGN_BOTTOM_MID, 0, -2);

    ubo_status_bar_reapply();
}
