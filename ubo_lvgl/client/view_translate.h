/* Translate decoded proto view messages into libubo_lvgl render calls.
 *
 * C port of the Python ubo_lvgl_gui_client/view_translator.py: maps the gRPC
 * view model onto the renderer's C view model (ubo_lvgl.h), reproducing the
 * Kivy-markup stripping, color mapping, double-wrapped item unwrapping and
 * notification slot handling.
 */
#ifndef UBO_VIEW_TRANSLATE_H
#define UBO_VIEW_TRANSLATE_H

#include <stddef.h>
#include <stdint.h>

/* Render current_view: decode the concrete view message (identified by the Any
 * type_url, e.g. ".../HomeViewData") from `value` and call the matching
 * ubo_lvgl_render_*. If the view is a frame_stream view and out_stream_id is
 * non-NULL, *out_stream_id is set to a malloc'd copy of the stream id (caller
 * frees); otherwise it is set to NULL. */
void ubo_view_render(const char *type_url, const uint8_t *value, size_t value_len,
                     char **out_stream_id);

/* Decode a StatusBarData from `value` and apply it via ubo_lvgl_set_status_bar. */
void ubo_view_render_status_bar(const uint8_t *value, size_t value_len);

#endif /* UBO_VIEW_TRANSLATE_H */
