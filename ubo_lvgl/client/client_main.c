/* Native C LVGL GUI client — entry point.
 *
 * Speaks gRPC-Web over HTTP/1.1 to ubo-core's Envoy proxy, decodes protobuf with
 * nanopb, and drives the libubo_lvgl renderer. macOS-first; the transport/codec
 * layers are written to port to ESP-IDF later.
 *
 * Threading (mirrors the Python web-grpc client):
 *   - main thread  : LVGL/SDL loop (ubo_lvgl_run blocks); input callback fires
 *                    here and enqueues key events.
 *   - store thread : SubscribeStore([current_view, status_bar, is_blanked]) ->
 *                    render; owns reconnect/backoff + the disconnect overlay.
 *   - event thread : SubscribeEvent([app_scroll, menu_choose, frame_stream]) ->
 *                    local interaction / live frames.
 *   - dispatch thd : drains the key queue and POSTs DispatchAction, so the input
 *                    thread never blocks on the network.
 */

#include <pthread.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "client_config.h"
#include "client_core.h"
#include "keymap.h"
#include "ubo_client.pb.h"
#include "ubo_lvgl.h"
#include "ubo_rpc.h"

#define QUEUE_CAP 32
#define KEY_MAX 8
#define STREAM_ID_MAX 128

/* Module-level shared state (single instance; not scattered globals). */
static struct {
    ubo_rpc *rpc;
    volatile bool stop;

    /* key dispatch queue */
    pthread_mutex_t qlock;
    pthread_cond_t qcond;
    char queue[QUEUE_CAP][KEY_MAX];
    int qhead, qtail, qcount;

    /* connection / overlay state (store thread) */
    bool connected;

    /* active frame_stream id (set by store thread, read by event thread) */
    pthread_mutex_t fslock;
    char active_stream[STREAM_ID_MAX];
} app;

static void sleep_ms(int ms) {
    struct timespec ts = {ms / 1000, (long)(ms % 1000) * 1000000L};
    nanosleep(&ts, NULL);
}

/* ── store stream ── */
/* Runs inside ubo_client_handle_store after each view render; tracks the
 * active frame_stream id so the event thread can filter frame events. */
static void on_stream_id(void *user, const char *stream_id) {
    (void)user;
    pthread_mutex_lock(&app.fslock);
    snprintf(app.active_stream, STREAM_ID_MAX, "%s", stream_id);
    pthread_mutex_unlock(&app.fslock);
    if (getenv("UBO_CLIENT_DEBUG") && stream_id[0]) {
        fprintf(stderr, "[store] active frame stream = %s\n", stream_id);
    }
}

static void on_store(void *user, const ubo_client_Any *results, size_t count) {
    (void)user;
    ubo_client_handle_store(results, count, &app.connected, on_stream_id, NULL);
}

static void *store_thread(void *arg) {
    (void)arg;
    const char *sel[] = {"state.main.current_view", "state.main.status_bar",
                         "state.display.is_blanked"};
    ubo_client_backoff bo;
    ubo_client_backoff_init(&bo);
    while (!app.stop) {
        time_t start = time(NULL);
        ubo_rpc_subscribe_store(app.rpc, sel, 3, on_store, NULL, &app.stop);
        if (app.stop) {
            break;
        }
        /* disconnected */
        app.connected = false;
        sleep_ms(ubo_client_backoff_step(&bo, time(NULL) - start, true));
    }
    return NULL;
}

/* ── event stream ── */
static void on_event(void *user, const ubo_client_Event *ev) {
    (void)user;
    if (ubo_client_handle_event_common(ev)) {
        return;
    }
    switch (ev->which_event) {
    case ubo_client_Event_frame_stream_data_event_tag: {
        const ubo_client_FrameStreamDataEvent *e = ev->event.frame_stream_data_event;
        if (!e || !e->stream_id || !e->data) {
            break;
        }
        bool match;
        pthread_mutex_lock(&app.fslock);
        match = strcmp(app.active_stream, e->stream_id) == 0;
        pthread_mutex_unlock(&app.fslock);
        if (match) {
            int w = e->width ? (int)*e->width : 0;
            int h = e->height ? (int)*e->height : 0;
            if (w > 0 && h > 0) {
                ubo_lvgl_update_frame(e->data->bytes, e->data->size, w, h);
            }
        }
        break;
    }
    default:
        break;
    }
}

static void *event_thread(void *arg) {
    (void)arg;
    /* One consolidated subscription for the three event kinds the client needs.
     * NB: vs the Python client this keeps frame_stream always-subscribed and
     * filters by the active stream id, rather than dynamically (un)subscribing —
     * a bandwidth refinement deferred to the ESP-IDF phase. */
    ubo_client_ApplicationScrollEvent ase = ubo_client_ApplicationScrollEvent_init_zero;
    ubo_client_MenuChooseByIndexEvent mce = ubo_client_MenuChooseByIndexEvent_init_zero;
    ubo_client_FrameStreamDataEvent fse = ubo_client_FrameStreamDataEvent_init_zero;
    ubo_client_Event evs[3];
    memset(evs, 0, sizeof(evs));
    evs[0].which_event = ubo_client_Event_application_scroll_event_tag;
    evs[0].event.application_scroll_event = &ase;
    evs[1].which_event = ubo_client_Event_menu_choose_by_index_event_tag;
    evs[1].event.menu_choose_by_index_event = &mce;
    evs[2].which_event = ubo_client_Event_frame_stream_data_event_tag;
    evs[2].event.frame_stream_data_event = &fse;

    ubo_client_backoff bo;
    ubo_client_backoff_init(&bo);
    while (!app.stop) {
        time_t start = time(NULL);
        int rc = ubo_rpc_subscribe_event(app.rpc, evs, 3, on_event, NULL, &app.stop);
        if (getenv("UBO_CLIENT_DEBUG")) {
            fprintf(stderr, "[event] subscribe_event returned %d (uptime %llds)\n",
                    rc, (long long)(time(NULL) - start));
        }
        if (app.stop) {
            break;
        }
        sleep_ms(ubo_client_backoff_step(&bo, time(NULL) - start, false));
    }
    return NULL;
}

/* ── dispatch worker ── */
static void *dispatch_thread(void *arg) {
    (void)arg;
    for (;;) {
        pthread_mutex_lock(&app.qlock);
        while (app.qcount == 0 && !app.stop) {
            pthread_cond_wait(&app.qcond, &app.qlock);
        }
        if (app.stop && app.qcount == 0) {
            pthread_mutex_unlock(&app.qlock);
            break;
        }
        char key[KEY_MAX];
        memcpy(key, app.queue[app.qhead], KEY_MAX);
        app.qhead = (app.qhead + 1) % QUEUE_CAP;
        app.qcount--;
        pthread_mutex_unlock(&app.qlock);
        ubo_keymap_dispatch(app.rpc, key);
    }
    return NULL;
}

/* ── input (main thread) ── */
static void on_input(const char *key, bool pressed, void *user) {
    (void)user;
    if (!pressed) {
        return; /* act on key-down only, matching the Python client */
    }
    pthread_mutex_lock(&app.qlock);
    if (app.qcount < QUEUE_CAP) {
        snprintf(app.queue[app.qtail], KEY_MAX, "%s", key);
        app.qtail = (app.qtail + 1) % QUEUE_CAP;
        app.qcount++;
        pthread_cond_signal(&app.qcond);
    }
    pthread_mutex_unlock(&app.qlock);
}

/* Headless test hook: feed comma-separated keys (e.g. "L1,HOME") through the
 * real on_input entry point SDL uses, so the queue/dispatch/keymap path can be
 * verified without driving an SDL window. Enabled via UBO_CLIENT_TEST_KEYS. */
static void *test_keys_thread(void *arg) {
    char *keys = strdup((const char *)arg);
    if (!keys) {
        return NULL;
    }
    sleep_ms(3000);
    for (char *tok = strtok(keys, ","); tok && !app.stop;
         tok = strtok(NULL, ",")) {
        on_input(tok, true, NULL);
        sleep_ms(1500);
    }
    free(keys);
    return NULL;
}

static ubo_backend_t backend_of(const char *name) {
    if (strcmp(name, "st7789") == 0) {
        return UBO_BACKEND_ST7789;
    }
    if (strcmp(name, "buffer") == 0) {
        return UBO_BACKEND_BUFFER;
    }
    return UBO_BACKEND_SDL;
}

int main(int argc, char **argv) {
    ubo_client_config cfg;
    if (!ubo_client_config_parse(argc, argv, &cfg)) {
        return 1;
    }

    ubo_lvgl_config lc = {
        .backend = backend_of(cfg.backend), .width = 240, .height = 240};
    if (ubo_lvgl_init(&lc) != 0) {
        fprintf(stderr, "lvgl init failed\n");
        return 2;
    }
    ubo_lvgl_set_input_cb(on_input, NULL);

    app.rpc = ubo_rpc_create(cfg.web_grpc_url);
    if (!app.rpc) {
        fprintf(stderr, "rpc create failed (%s)\n", cfg.web_grpc_url);
        return 2;
    }
    pthread_mutex_init(&app.qlock, NULL);
    pthread_cond_init(&app.qcond, NULL);
    pthread_mutex_init(&app.fslock, NULL);

    fprintf(stderr, "ubo_lvgl_client: backend=%s url=%s\n", cfg.backend,
            cfg.web_grpc_url);

    pthread_t t_store, t_event, t_dispatch;
    if (pthread_create(&t_store, NULL, store_thread, NULL) != 0 ||
        pthread_create(&t_event, NULL, event_thread, NULL) != 0 ||
        pthread_create(&t_dispatch, NULL, dispatch_thread, NULL) != 0) {
        fprintf(stderr, "failed to start client worker threads\n");
        return 2;
    }

    const char *test_keys = getenv("UBO_CLIENT_TEST_KEYS");
    pthread_t t_test;
    bool have_test = test_keys && test_keys[0];
    if (have_test &&
        pthread_create(&t_test, NULL, test_keys_thread, (void *)test_keys) != 0) {
        fprintf(stderr, "failed to start test-keys thread\n");
        have_test = false;
    }

    ubo_lvgl_run(false); /* blocks until the window closes */

    /* Shut down: signal stop, wake the dispatch worker, let streams abort. */
    app.stop = true;
    pthread_mutex_lock(&app.qlock);
    pthread_cond_signal(&app.qcond);
    pthread_mutex_unlock(&app.qlock);
    if (have_test) {
        pthread_join(t_test, NULL);
    }
    pthread_join(t_store, NULL);
    pthread_join(t_event, NULL);
    pthread_join(t_dispatch, NULL);

    ubo_rpc_destroy(app.rpc);
    ubo_lvgl_shutdown();
    return 0;
}
