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
static lv_obj_t *s_disc_sub;    /* "Reconnecting in Ns (attempt A/M)" subtitle */
static lv_obj_t *s_disc_switch; /* optional "Use WiFi" / "Use USB" touch target */
static lv_obj_t *s_prov;        /* WiFi setup / captive-portal instructions cover */

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
    lv_obj_set_style_text_font(name, UBO_FONT_XXL, 0);
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
    lv_obj_set_style_text_font(icon, UBO_FONT_ICON, 0);
    lv_obj_set_style_text_color(icon, lv_color_hex(0xE53935), 0);
    lv_label_set_text(icon, "\U000F02FC"); /* information/alert glyph */

    lv_obj_t *lbl = lv_label_create(s_disc);
    lv_obj_set_style_text_color(lbl, lv_color_hex(0xE53935), 0);
    lv_obj_set_style_text_font(lbl, UBO_FONT_LG, 0);
    lv_label_set_text(lbl, "Disconnected");

    s_disc_sub = lv_label_create(s_disc);
    lv_label_set_long_mode(s_disc_sub, LV_LABEL_LONG_WRAP);
    lv_obj_set_width(s_disc_sub, UBO_W - 20);
    lv_obj_set_style_text_align(s_disc_sub, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_text_color(s_disc_sub, UBO_COL_MUTED, 0);
    lv_obj_set_style_text_font(s_disc_sub, UBO_FONT_SM, 0);
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

void ubo_overlay_disconnected_status(int attempt, int seconds)
{
    ensure_disc();
    if (seconds > 0) {
        lv_label_set_text_fmt(s_disc_sub, "Reconnecting in %ds (attempt %d)",
                              seconds, attempt);
    } else {
        lv_label_set_text_fmt(s_disc_sub, "Reconnecting... (attempt %d)",
                              attempt);
    }
    lv_obj_move_foreground(s_disc);
    lv_obj_clear_flag(s_disc, LV_OBJ_FLAG_HIDDEN);
}

/* The transport switch rides on the disconnect cover rather than being an overlay
 * of its own: that cover is raised by the client's reconnect backoff, which is
 * exactly when the link the user wants to escape from is the one that's failing.
 * During a healthy session there is nothing to escape and a button would just sit
 * on top of the core's UI. */
void ubo_overlay_transport_switch(const char *label)
{
    if (!label) {
        if (s_disc_switch) {
            lv_obj_add_flag(s_disc_switch, LV_OBJ_FLAG_HIDDEN);
        }
        return;
    }
    ensure_disc();
    if (!s_disc_switch) {
        s_disc_switch = lv_label_create(s_disc);
        lv_obj_set_width(s_disc_switch, UBO_W - 80); /* a generous touch target */
        lv_obj_set_style_text_align(s_disc_switch, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_set_style_text_color(s_disc_switch, UBO_COL_FG, 0);
        lv_obj_set_style_text_font(s_disc_switch, UBO_FONT_SM, 0);
        lv_obj_set_style_bg_color(s_disc_switch, lv_color_hex(0x303030), 0);
        lv_obj_set_style_bg_opa(s_disc_switch, LV_OPA_COVER, 0);
        lv_obj_set_style_radius(s_disc_switch, 6, 0);
        lv_obj_set_style_pad_all(s_disc_switch, 10, 0);
    }
    lv_label_set_text(s_disc_switch, label);
    lv_obj_clear_flag(s_disc_switch, LV_OBJ_FLAG_HIDDEN);
}

bool ubo_overlay_hit_transport_switch(int x, int y)
{
    if (!s_disc || !s_disc_switch) {
        return false;
    }
    /* Only hittable while the user can actually see it. */
    if (lv_obj_has_flag(s_disc, LV_OBJ_FLAG_HIDDEN) ||
        lv_obj_has_flag(s_disc_switch, LV_OBJ_FLAG_HIDDEN)) {
        return false;
    }
    lv_area_t a;
    lv_obj_get_coords(s_disc_switch, &a);
    return x >= a.x1 && x <= a.x2 && y >= a.y1 && y <= a.y2;
}

void ubo_overlay_provisioning(const char *ap_ssid, const char *ip)
{
    if (!s_prov) {
        s_prov = full_cover(UBO_COL_BG);

        lv_obj_t *icon = lv_label_create(s_prov);
        lv_obj_set_style_text_font(icon, UBO_FONT_ICON, 0);
        lv_obj_set_style_text_color(icon, UBO_COL_INFO, 0);
        lv_label_set_text(icon, "\U000F0928"); /* wifi glyph */

        lv_obj_t *title = lv_label_create(s_prov);
        lv_obj_set_style_text_color(title, UBO_COL_FG, 0);
        lv_obj_set_style_text_font(title, UBO_FONT_LG, 0);
        lv_label_set_text(title, "WiFi setup");

        lv_obj_t *sub = lv_label_create(s_prov);
        lv_label_set_long_mode(sub, LV_LABEL_LONG_WRAP);
        lv_obj_set_width(sub, UBO_W - 20);
        lv_obj_set_style_text_align(sub, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_set_style_text_color(sub, UBO_COL_MUTED, 0);
        lv_obj_set_style_text_font(sub, UBO_FONT_SM, 0);
        lv_label_set_text_fmt(sub, "Join WiFi '%s'\nthen open http://%s", ap_ssid,
                              ip);
    }
    lv_obj_move_foreground(s_prov);
    lv_obj_clear_flag(s_prov, LV_OBJ_FLAG_HIDDEN);
}
