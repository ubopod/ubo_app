/**
 * @file view_menu.c
 * Menu view: a title (in the header) plus the current page's item bars laid out
 * in the middle band so the centre item is always screen-centred. When the menu
 * is scrollable the previous/next items peek into the header/footer space
 * (covered by the bars on page 0, revealed once the status bar hides) — matching
 * ubo_gui's render_surroundings behaviour.
 */
#include "ubo_views.h"

void ubo_build_menu(const ubo_menu_view *v)
{
    ubo_screen_clear_content();
    lv_obj_t *page = ubo_screen_content();
    /* Header on the first page, footer on the last page (ubo_gui scroll bars). */
    ubo_screen_show_chrome(v->page_index == 0,
                           v->page_index == v->total_pages - 1);

    const char *title = (v->title && v->title[0]) ? v->title
                        : (v->heading ? v->heading : "");
    ubo_screen_set_title(title);

    const int count = v->item_count;

    /* Empty menu: show the placeholder centred in the band (ubo_gui HeadedMenu). */
    if (count == 0) {
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
    int start = 0;
    if (count > UBO_PAGE_SIZE && v->page_index > 0) {
        start = v->page_index * UBO_PAGE_SIZE;
    }
    int end = start + UBO_PAGE_SIZE;
    if (end > count) {
        end = count;
    }

    const bool scrollable = v->total_pages > 1;
    const bool has_prev = scrollable && start > 0;
    const bool has_next = scrollable && end < count;

    /* Item list, sized to its content and positioned so the main items land in
     * the band. Items leave room on the right for the page slider. */
    lv_obj_t *list = lv_obj_create(page);
    lv_obj_remove_style_all(list);
    lv_obj_clear_flag(list, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_width(list, UBO_W - (scrollable ? 14 : 6));
    lv_obj_set_height(list, LV_SIZE_CONTENT);
    lv_obj_set_flex_flow(list, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(list, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START,
                          LV_FLEX_ALIGN_START);
    lv_obj_set_style_pad_row(list, UBO_ITEM_GAP, 0);

    if (has_prev) {
        ubo_item_bar(list, &v->items[start - 1], false);
    }
    for (int i = start; i < end; i++) {
        ubo_item_bar(list, &v->items[i], false);
    }
    if (has_next) {
        ubo_item_bar(list, &v->items[end], false);
    }

    /* Top-align the main items at the band top so the items fill from the top
     * and the item in the centre slot is screen-centred. With a peek above,
     * shift up by one row. (Top-aligning means a 2-item page puts its second
     * item in the centre slot, a 3-item page its middle item.) */
    const int y = has_prev ? UBO_HEADER_H - (UBO_ITEM_H + UBO_ITEM_GAP)
                           : UBO_HEADER_H;
    lv_obj_set_pos(list, 0, y);

    ubo_screen_set_page_slider(v->page_index, v->total_pages);
    ubo_status_bar_reapply();
}
