#include "client_app.h"

#include <string.h>
#include <time.h>

#include <pb_decode.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#include "keymap.h"
#include "ubo_client.pb.h"
#include "ubo_lvgl.h"
#include "ubo_rpc.h"
#include "view_translate.h"

static const char *TAG = "ubo_client";

/* Reconnect policy (mirrors web_client.py / desktop client_main.c). */
#define RECONNECT_INITIAL_DELAY_MS 200
#define RECONNECT_MAX_DELAY_MS 30000
#define HEALTHY_STREAM_SECONDS 5
#define MAX_RECONNECT_ATTEMPTS 50

#define KEY_MAX 8
#define QUEUE_CAP 16

static struct {
    ubo_rpc *rpc;
    volatile bool stop;
    bool connected;
    QueueHandle_t keyq;
} st;

static bool type_is(const char *type_url, const char *name) {
    return type_url && strstr(type_url, name) != NULL;
}

/* ── store stream: [current_view, status_bar, is_blanked] ── */
static void on_store(void *user, const ubo_client_Any *results, size_t count) {
    (void)user;
    if (!st.connected) {
        st.connected = true;
        ubo_lvgl_set_connected(true);
    }
    if (count > 1 && results[1].value &&
        type_is(results[1].type_url, "StatusBarData")) {
        ubo_view_render_status_bar(results[1].value->bytes,
                                   results[1].value->size);
    }
    if (count > 0 && results[0].value) {
        /* out_stream_id = NULL: the camera viewfinder is deferred on-device. */
        ubo_view_render(results[0].type_url, results[0].value->bytes,
                        results[0].value->size, NULL);
    }
    if (count > 2 && results[2].value &&
        type_is(results[2].type_url, "BoolValue")) {
        ubo_client_BoolValue bv = ubo_client_BoolValue_init_zero;
        pb_istream_t is = pb_istream_from_buffer(results[2].value->bytes,
                                                 results[2].value->size);
        if (pb_decode(&is, ubo_client_BoolValue_fields, &bv)) {
            ubo_lvgl_set_blanked(bv.value);
        }
    }
}

static void store_task(void *arg) {
    (void)arg;
    const char *sel[] = {"state.main.current_view", "state.main.status_bar",
                         "state.display.is_blanked"};
    int delay = RECONNECT_INITIAL_DELAY_MS;
    int attempt = 0;
    while (!st.stop) {
        time_t start = time(NULL);
        ubo_rpc_subscribe_store(st.rpc, sel, 3, on_store, NULL, &st.stop);
        if (st.stop) {
            break;
        }
        st.connected = false;
        if (time(NULL) - start >= HEALTHY_STREAM_SECONDS) {
            delay = RECONNECT_INITIAL_DELAY_MS;
            attempt = 0;
        }
        attempt++;
        ubo_lvgl_set_disconnect_status(attempt, MAX_RECONNECT_ATTEMPTS,
                                       delay / 1000);
        vTaskDelay(pdMS_TO_TICKS(delay));
        delay = delay * 2 > RECONNECT_MAX_DELAY_MS ? RECONNECT_MAX_DELAY_MS
                                                   : delay * 2;
    }
    vTaskDelete(NULL);
}

/* ── event stream: application_scroll + menu_choose (no frame_stream) ── */
static void on_event(void *user, const ubo_client_Event *ev) {
    (void)user;
    switch (ev->which_event) {
    case ubo_client_Event_application_scroll_event_tag: {
        const ubo_client_ApplicationScrollEvent *e =
            ev->event.application_scroll_event;
        if (e && e->direction) {
            ubo_lvgl_render_scroll(e->direction);
        }
        break;
    }
    case ubo_client_Event_menu_choose_by_index_event_tag: {
        const ubo_client_MenuChooseByIndexEvent *e =
            ev->event.menu_choose_by_index_event;
        ubo_lvgl_render_choose(e && e->index ? (int)*e->index : 0);
        break;
    }
    default:
        break;
    }
}

static void event_task(void *arg) {
    (void)arg;
    ubo_client_ApplicationScrollEvent ase =
        ubo_client_ApplicationScrollEvent_init_zero;
    ubo_client_MenuChooseByIndexEvent mce =
        ubo_client_MenuChooseByIndexEvent_init_zero;
    ubo_client_Event evs[2];
    memset(evs, 0, sizeof(evs));
    evs[0].which_event = ubo_client_Event_application_scroll_event_tag;
    evs[0].event.application_scroll_event = &ase;
    evs[1].which_event = ubo_client_Event_menu_choose_by_index_event_tag;
    evs[1].event.menu_choose_by_index_event = &mce;

    int delay = RECONNECT_INITIAL_DELAY_MS;
    while (!st.stop) {
        time_t start = time(NULL);
        ubo_rpc_subscribe_event(st.rpc, evs, 2, on_event, NULL, &st.stop);
        if (st.stop) {
            break;
        }
        if (time(NULL) - start >= HEALTHY_STREAM_SECONDS) {
            delay = RECONNECT_INITIAL_DELAY_MS;
        }
        vTaskDelay(pdMS_TO_TICKS(delay));
        delay = delay * 2 > RECONNECT_MAX_DELAY_MS ? RECONNECT_MAX_DELAY_MS
                                                   : delay * 2;
    }
    vTaskDelete(NULL);
}

/* ── dispatch worker ── */
static volatile int s_pending_vol = -1; /* 0..100, -1 = none */

void ubo_client_set_volume(int level) {
    s_pending_vol = level < 0 ? 0 : (level > 100 ? 100 : level);
}

static void dispatch_task(void *arg) {
    (void)arg;
    char key[KEY_MAX];
    while (!st.stop) {
        /* Send the latest pending volume (coalesced), then drain a key with a
         * short timeout so volume slides stay responsive. */
        const int v = s_pending_vol;
        if (v >= 0) {
            s_pending_vol = -1;
            ubo_keymap_set_volume(st.rpc, (float)v / 100.0f);
        }
        if (xQueueReceive(st.keyq, key, pdMS_TO_TICKS(40)) == pdTRUE) {
            ubo_keymap_dispatch(st.rpc, key);
        }
    }
    vTaskDelete(NULL);
}

void ubo_client_enqueue_key(const char *key) {
    if (!st.keyq || !key) {
        return;
    }
    char buf[KEY_MAX];
    snprintf(buf, sizeof(buf), "%s", key);
    xQueueSend(st.keyq, buf, 0);
}

void ubo_client_start(const char *web_grpc_url) {
    st.rpc = ubo_rpc_create(web_grpc_url);
    if (!st.rpc) {
        ESP_LOGE(TAG, "rpc create failed (%s)", web_grpc_url);
        return;
    }
    st.keyq = xQueueCreate(QUEUE_CAP, KEY_MAX);
    xTaskCreate(store_task, "ubo_store", 8192, NULL, 5, NULL);
    xTaskCreate(event_task, "ubo_event", 6144, NULL, 5, NULL);
    xTaskCreate(dispatch_task, "ubo_disp", 4096, NULL, 5, NULL);
    ESP_LOGI(TAG, "client started -> %s", web_grpc_url);
}
