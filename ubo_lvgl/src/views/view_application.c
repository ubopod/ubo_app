/**
 * @file view_application.c
 * Application view: phase-1 placeholder. The real per-application widgets and
 * the local application registry land in phase 1.5.
 */
#include "ubo_views.h"

void ubo_build_application(const ubo_application_view *v)
{
    ubo_screen_show_chrome(v->show_status_bar, v->show_status_bar);
    const char *id = (v->application_id && v->application_id[0])
                         ? v->application_id
                         : "application";
    ubo_screen_set_title(id);

    ubo_screen_clear_content();
    lv_obj_t *c = ubo_screen_content();
    lv_obj_set_flex_flow(c, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(c, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER);

    lv_obj_t *lbl = lv_label_create(c);
    lv_obj_set_style_text_align(lbl, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_text_color(lbl, UBO_COL_MUTED, 0);
    lv_obj_set_style_text_font(lbl, UBO_FONT_MD, 0);
    lv_label_set_text_fmt(lbl, "Application\n%s", id);

    ubo_status_bar_reapply();
}
