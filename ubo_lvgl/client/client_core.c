#include "client_core.h"

#include <string.h>

#include <pb_decode.h>

#include "client_log.h"
#include "ubo_lvgl.h"
#include "view_translate.h"

#include <stdlib.h>

#define RECONNECT_INITIAL_DELAY_MS 200
#define RECONNECT_MAX_DELAY_MS 30000
#define HEALTHY_STREAM_SECONDS 5

void ubo_client_backoff_init(ubo_client_backoff *b) {
    b->delay_ms = RECONNECT_INITIAL_DELAY_MS;
    b->attempt = 0;
}

int ubo_client_backoff_step(ubo_client_backoff *b, long stream_seconds,
                            bool show_overlay) {
    if (stream_seconds >= HEALTHY_STREAM_SECONDS) {
        ubo_client_backoff_init(b);
    }
    b->attempt++;
    int delay = b->delay_ms;
    if (show_overlay) {
        ubo_lvgl_set_disconnect_status(b->attempt, delay / 1000);
    }
    b->delay_ms = delay * 2 > RECONNECT_MAX_DELAY_MS ? RECONNECT_MAX_DELAY_MS
                                                     : delay * 2;
    return delay;
}

static bool type_is(const char *type_url, const char *name) {
    return type_url && strstr(type_url, name) != NULL;
}

/* FNV-1a, for cheap change-detection of the re-delivered selector blobs. */
static uint32_t blob_hash(const uint8_t *b, size_t n) {
    uint32_t h = 2166136261u;
    for (size_t i = 0; i < n; i++) {
        h = (h ^ b[i]) * 16777619u;
    }
    return h;
}

void ubo_client_handle_store(const ubo_client_Any *results, size_t count,
                             bool *connected,
                             ubo_client_stream_id_cb on_stream_id, void *user) {
    if (connected && !*connected) {
        *connected = true;
        ubo_lvgl_set_connected(true);
    }
    /* results: [current_view, status_bar, is_blanked] */
    static uint32_t last_view, last_sbar;
    if (count > 1 && results[1].value &&
        type_is(results[1].type_url, "StatusBarData")) {
        uint32_t h = blob_hash(results[1].value->bytes, results[1].value->size);
        if (h != last_sbar) {
            last_sbar = h;
            ubo_view_render_status_bar(results[1].value->bytes,
                                       results[1].value->size);
        }
    }
    if (count > 0 && results[0].value) {
        uint32_t h = blob_hash(results[0].value->bytes, results[0].value->size);
        if (h != last_view) {
            last_view = h;
            char *stream_id = NULL;
            ubo_view_render(results[0].type_url, results[0].value->bytes,
                            results[0].value->size,
                            on_stream_id ? &stream_id : NULL);
            if (on_stream_id) {
                on_stream_id(user, stream_id ? stream_id : "");
            }
            free(stream_id);
        }
    }
    if (count > 2 && results[2].value &&
        type_is(results[2].type_url, "BoolValue")) {
        ubo_client_BoolValue bv = ubo_client_BoolValue_init_zero;
        pb_istream_t is = pb_istream_from_buffer(results[2].value->bytes,
                                                 results[2].value->size);
        if (pb_decode(&is, ubo_client_BoolValue_fields, &bv)) {
            ubo_lvgl_set_blanked(bv.value);
        } else {
            UBO_CLIENT_LOGW("pb_decode failed for is_blanked BoolValue");
        }
    }
}

bool ubo_client_handle_event_common(const ubo_client_Event *ev) {
    switch (ev->which_event) {
    case ubo_client_Event_application_scroll_event_tag: {
        const ubo_client_ApplicationScrollEvent *e =
            ev->event.application_scroll_event;
        if (e && e->direction) {
            ubo_lvgl_render_scroll(e->direction);
        }
        return true;
    }
    case ubo_client_Event_menu_choose_by_index_event_tag: {
        const ubo_client_MenuChooseByIndexEvent *e =
            ev->event.menu_choose_by_index_event;
        ubo_lvgl_render_choose(e && e->index ? (int)*e->index : 0);
        return true;
    }
    default:
        return false;
    }
}
