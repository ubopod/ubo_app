/**
 * @file overlays.c
 * Full-screen overlays drawn on LVGL's top layer so they cover the view chrome:
 *   - splash      : shown at startup, hidden on the first view render
 *   - blank       : black cover when the core blanks the display
 *   - disconnected: red cover when the gRPC link is down
 */
#include "ubo_views.h"

static lv_obj_t *s_splash;
static lv_obj_t *s_blank;
static lv_obj_t *s_disc;
static lv_obj_t *s_disc_sub; /* "Reconnecting in Ns (attempt A/M)" subtitle */

static lv_obj_t *full_cover(lv_color_t bg)
{
    lv_obj_t *o = lv_obj_create(lv_layer_top());
    lv_obj_remove_style_all(o);
    lv_obj_set_size(o, UBO_W, UBO_H);
    lv_obj_set_pos(o, 0, 0);
    lv_obj_set_style_bg_color(o, bg, 0);
    lv_obj_set_style_bg_opa(o, LV_OPA_COVER, 0);
    lv_obj_clear_flag(o, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_flex_flow(o, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(o, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_row(o, 10, 0);
    return o;
}

void ubo_overlay_splash_show(void)
{
    if (s_splash) {
        lv_obj_clear_flag(s_splash, LV_OBJ_FLAG_HIDDEN);
        return;
    }
    s_splash = full_cover(UBO_COL_BG);

    lv_obj_t *name = lv_label_create(s_splash);
    lv_obj_set_style_text_color(name, UBO_COL_FG, 0);
    lv_obj_set_style_text_font(name, &lv_font_montserrat_28, 0);
    lv_label_set_text(name, "ubo");

    lv_obj_t *sp = lv_spinner_create(s_splash);
    lv_obj_set_size(sp, 36, 36);
    lv_obj_set_style_arc_color(sp, lv_color_hex(0x303030), LV_PART_MAIN);
    lv_obj_set_style_arc_color(sp, UBO_COL_INFO, LV_PART_INDICATOR);
    lv_obj_set_style_arc_width(sp, 4, LV_PART_MAIN);
    lv_obj_set_style_arc_width(sp, 4, LV_PART_INDICATOR);
}

void ubo_overlay_splash_hide(void)
{
    if (s_splash) {
        lv_obj_add_flag(s_splash, LV_OBJ_FLAG_HIDDEN);
    }
}

void ubo_overlay_blank(bool on)
{
    if (on) {
        if (!s_blank) {
            s_blank = full_cover(lv_color_black());
        }
        lv_obj_move_foreground(s_blank);
        lv_obj_clear_flag(s_blank, LV_OBJ_FLAG_HIDDEN);
    } else if (s_blank) {
        lv_obj_add_flag(s_blank, LV_OBJ_FLAG_HIDDEN);
    }
}

static void ensure_disc(void)
{
    if (s_disc) {
        return;
    }
    s_disc = full_cover(lv_color_hex(0x000000));
    lv_obj_t *icon = lv_label_create(s_disc);
    lv_obj_set_style_text_font(icon, ubo_font_icon_18(), 0);
    lv_obj_set_style_text_color(icon, lv_color_hex(0xE53935), 0);
    lv_label_set_text(icon, "\U000F02FC"); /* information/alert glyph */

    lv_obj_t *lbl = lv_label_create(s_disc);
    lv_obj_set_style_text_color(lbl, lv_color_hex(0xE53935), 0);
    lv_obj_set_style_text_font(lbl, &lv_font_montserrat_18, 0);
    lv_label_set_text(lbl, "Disconnected");

    s_disc_sub = lv_label_create(s_disc);
    lv_label_set_long_mode(s_disc_sub, LV_LABEL_LONG_WRAP);
    lv_obj_set_width(s_disc_sub, UBO_W - 20);
    lv_obj_set_style_text_align(s_disc_sub, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_text_color(s_disc_sub, UBO_COL_MUTED, 0);
    lv_obj_set_style_text_font(s_disc_sub, &lv_font_montserrat_14, 0);
    lv_label_set_text(s_disc_sub, "");
}

void ubo_overlay_disconnected(bool shown)
{
    if (shown) {
        ensure_disc();
        lv_obj_move_foreground(s_disc);
        lv_obj_clear_flag(s_disc, LV_OBJ_FLAG_HIDDEN);
    } else if (s_disc) {
        lv_obj_add_flag(s_disc, LV_OBJ_FLAG_HIDDEN);
    }
}

void ubo_overlay_disconnected_status(int attempt, int max_attempts, int seconds)
{
    ensure_disc();
    if (seconds > 0) {
        lv_label_set_text_fmt(s_disc_sub, "Reconnecting in %ds (attempt %d/%d)",
                              seconds, attempt, max_attempts);
    } else {
        lv_label_set_text_fmt(s_disc_sub, "Reconnecting... (attempt %d/%d)",
                              attempt, max_attempts);
    }
    lv_obj_move_foreground(s_disc);
    lv_obj_clear_flag(s_disc, LV_OBJ_FLAG_HIDDEN);
}
