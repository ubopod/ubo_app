/* Platform-neutral client logic shared by the desktop entry (client_main.c,
 * pthreads) and the ESP32 firmware (esp32/main/client_app.c, FreeRTOS tasks).
 * The store/event stream handling and the reconnect policy live here exactly
 * once so the two targets cannot drift behaviorally; the platform files keep
 * only thread/task plumbing and their target-specific event cases. */
#ifndef UBO_CLIENT_CORE_H
#define UBO_CLIENT_CORE_H

#include <stdbool.h>
#include <stddef.h>

#include "ubo_client.pb.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ── Reconnect/backoff policy (mirrors web_client.py) ──
 * Exponential 200ms → 30s, reset to the initial delay after a stream that
 * stayed healthy for >= 5s. Retries forever: the client is an appliance and
 * must self-heal whenever the core comes back, so there is deliberately no
 * attempt cap. */
typedef struct {
    int delay_ms; /* delay to sleep before the NEXT attempt */
    int attempt;  /* attempts since the last healthy stream */
} ubo_client_backoff;

void ubo_client_backoff_init(ubo_client_backoff *b);

/* Account for a stream that ended after `stream_seconds`. Returns the delay in
 * ms the caller must sleep before reconnecting. When `show_overlay` is true the
 * disconnect overlay subtitle is updated (store stream only — the event stream
 * backs off silently alongside it). */
int ubo_client_backoff_step(ubo_client_backoff *b, long stream_seconds,
                            bool show_overlay);

/* ── SubscribeStore handling ──
 * One delivery is [current_view, status_bar, is_blanked]; the server re-sends
 * ALL selectors whenever ANY one changes, so each part is applied only when its
 * bytes actually changed (FNV hash) — an unrelated status tick must not rebuild
 * and re-animate the current view mid page-transition. The hashes track what is
 * on screen, so they stay correct across reconnects too.
 *
 * `*connected` is flipped to true (and the disconnect overlay hidden) on the
 * first delivery after a drop; the caller resets it to false when its stream
 * ends. When `on_stream_id` is non-NULL it receives the active frame_stream id
 * ("" when the current view has none) after every view render — the desktop
 * build uses it to filter FrameStreamDataEvents; the ESP32 build passes NULL
 * (camera viewfinder deferred on-device). */
typedef void (*ubo_client_stream_id_cb)(void *user, const char *stream_id);

void ubo_client_handle_store(const ubo_client_Any *results, size_t count,
                             bool *connected,
                             ubo_client_stream_id_cb on_stream_id, void *user);

/* ── SubscribeEvent handling ──
 * Consumes the events every target subscribes to (application_scroll,
 * menu_choose_by_index). Returns true when consumed; false lets the caller
 * handle its target-specific extras (audio playback on ESP32, frame_stream on
 * desktop) or ignore the event. */
bool ubo_client_handle_event_common(const ubo_client_Event *ev);

#ifdef __cplusplus
}
#endif
#endif /* UBO_CLIENT_CORE_H */
