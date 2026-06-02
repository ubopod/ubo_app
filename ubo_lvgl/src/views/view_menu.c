/**
 * @file view_menu.c
 * Menu view. Items occupy a continuous grid of "slots" (height 52, gap 7) that
 * line up with the L1/L2/L3 buttons; each page shows three slots.
 *
 * Matches ubo_gui's pagination (compute_total_pages / HEADED_MENU_HEADER_SLOTS):
 *   - A HEADED menu (heading set) reserves the first two slots for the heading
 *     and sub_heading, so item 0 lands on L3 of page 0 and the items continue on
 *     the following pages.
 *   - A HEADLESS menu has no header slots, so its items fill from L1.
 *   - A scrollable menu reveals the previous/next slot peeking into the
 *     header/footer space.
 */
#include "ubo_views.h"

#define UBO_HEADER_SLOTS 2 /* mirrors ubo_app HEADED_MENU_HEADER_SLOTS */

static lv_obj_t *slot_box(lv_obj_t *list)
{
    lv_obj_t *s = lv_obj_create(list);
    lv_obj_remove_style_all(s);
    lv_obj_clear_flag(s, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_size(s, lv_pct(100), UBO_ITEM_H);
    return s;
}

static void add_text_slot(lv_obj_t *list, const char *text, const lv_font_t *font,
                          lv_color_t color)
{
    lv_obj_t *s = slot_box(list);
    lv_obj_t *l = lv_label_create(s);
    lv_label_set_long_mode(l, LV_LABEL_LONG_WRAP);
    lv_obj_set_width(l, lv_pct(100));
    lv_obj_set_style_text_align(l, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_text_font(l, font, 0);
    lv_obj_set_style_text_color(l, color, 0);
    lv_label_set_text(l, text ? text : "");
    lv_obj_center(l);
}

/* Render the content of global slot `g`: heading (slot 0), sub_heading (slot 1)
 * for a headed menu, otherwise the item at `g - header_slots` (or a blank slot
 * to keep the L1/L2/L3 positions fixed). */
static void add_slot(lv_obj_t *list, const ubo_menu_view *v, int g, int header_slots)
{
    if (header_slots > 0 && g == 0) {
        add_text_slot(list, v->heading, &lv_font_montserrat_20, UBO_COL_FG);
    } else if (header_slots > 0 && g == 1) {
        add_text_slot(list, v->sub_heading, &lv_font_montserrat_14, UBO_COL_MUTED);
    } else {
        const int idx = g - header_slots;
        if (idx >= 0 && idx < v->item_count) {
            ubo_item_bar(list, &v->items[idx], false);
        } else {
            slot_box(list);
        }
    }
}

void ubo_build_menu(const ubo_menu_view *v)
{
    ubo_screen_clear_content();
    lv_obj_t *page = ubo_screen_content();
    /* Header on the first page, footer on the last page (ubo_gui scroll bars). */
    ubo_screen_show_chrome(v->page_index == 0,
                           v->page_index == v->total_pages - 1);
    ubo_screen_set_title((v->title && v->title[0]) ? v->title : "");

    const bool headed = v->heading && v->heading[0];
    const int hs = headed ? UBO_HEADER_SLOTS : 0;
    const int count = v->item_count;

    /* Empty headless menu: show the placeholder centred (ubo_gui HeadlessMenu). */
    if (count == 0 && !headed) {
        const char *ph = (v->placeholder && v->placeholder[0]) ? v->placeholder
                                                               : "";
        lv_obj_t *lbl = lv_label_create(page);
        lv_obj_set_style_text_font(lbl, &lv_font_montserrat_16, 0);
        lv_obj_set_style_text_color(lbl, UBO_COL_MUTED, 0);
        lv_obj_set_style_text_align(lbl, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_set_width(lbl, UBO_W - 24);
        lv_label_set_long_mode(lbl, LV_LABEL_LONG_WRAP);
        lv_label_set_text(lbl, ph);
        lv_obj_align(lbl, LV_ALIGN_CENTER, 0, 0);
        ubo_screen_set_page_slider(v->page_index, v->total_pages);
        ubo_status_bar_reapply();
        return;
    }

    const int p = v->page_index;
    const bool scrollable = v->total_pages > 1;
    const bool peek_above = scrollable && p > 0;
    const int below_g = UBO_PAGE_SIZE * p + UBO_PAGE_SIZE;
    const bool peek_below =
        scrollable && (below_g - hs) >= 0 && (below_g - hs) < count;

    /* The list holds the three slots for this page (plus the peeking neighbours),
     * positioned so the main slots land on L1/L2/L3. */
    lv_obj_t *list = lv_obj_create(page);
    lv_obj_remove_style_all(list);
    lv_obj_clear_flag(list, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_width(list, UBO_W - (scrollable ? 14 : 6));
    lv_obj_set_height(list, LV_SIZE_CONTENT);
    lv_obj_set_flex_flow(list, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(list, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START,
                          LV_FLEX_ALIGN_START);
    lv_obj_set_style_pad_row(list, UBO_ITEM_GAP, 0);

    if (peek_above) {
        ubo_item_bar(list, &v->items[(UBO_PAGE_SIZE * p - 1) - hs], false);
    }
    for (int k = 0; k < UBO_PAGE_SIZE; k++) {
        add_slot(list, v, UBO_PAGE_SIZE * p + k, hs);
    }
    if (peek_below) {
        ubo_item_bar(list, &v->items[below_g - hs], false);
    }

    /* With a peek above, shift the list up one row so the main slots stay on
     * their buttons and the previous item peeks into the header space. */
    const int y = peek_above ? UBO_HEADER_H - (UBO_ITEM_H + UBO_ITEM_GAP)
                             : UBO_HEADER_H;
    lv_obj_set_pos(list, 0, y);

    ubo_screen_set_page_slider(v->page_index, v->total_pages);
    ubo_status_bar_reapply();
}
