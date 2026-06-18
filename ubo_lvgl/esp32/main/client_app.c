#include "client_app.h"

#include <string.h>
#include <time.h>

#include <pb_decode.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

#include "audio.h"
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

/* ── PTT mic handoff: the audio capture task fills one of two pre-wrapped
 * pb_bytes_array_t buffers and publishes its index; the dispatch worker (the
 * single HTTP owner) sends it. Ping-pong + a single `ready` slot give
 * drop-oldest without blocking capture. 500ms @ 16kHz/16-bit/mono = 16000B. */
#define MIC_MAX_BYTES 16000
static struct {
    union {
        pb_bytes_array_t arr;
        uint8_t storage[PB_BYTES_ARRAY_T_ALLOCSIZE(MIC_MAX_BYTES)];
    } pp[2];
    float ts[2];
    int widx;            /* buffer the capture cb writes next */
    volatile int ready;  /* index ready to send, or -1 */
    SemaphoreHandle_t mtx;
} mic;

/* Runs on the audio mic task. Copy the chunk into the free ping-pong buffer and
 * publish it; never blocks on the network. */
static void mic_cb(void *user, const uint8_t *pcm, size_t len, float ts) {
    (void)user;
    if (len > MIC_MAX_BYTES) {
        len = MIC_MAX_BYTES;
    }
    int idx = mic.widx;
    memcpy(mic.pp[idx].arr.bytes, pcm, len);
    mic.pp[idx].arr.size = len;
    mic.ts[idx] = ts;
    xSemaphoreTake(mic.mtx, portMAX_DELAY);
    mic.ready = idx;
    mic.widx ^= 1;
    xSemaphoreGive(mic.mtx);
}

/* Send the published mic chunk, if any (called only from the dispatch worker). */
static void mic_drain(void) {
    int idx;
    xSemaphoreTake(mic.mtx, portMAX_DELAY);
    idx = mic.ready;
    mic.ready = -1;
    xSemaphoreGive(mic.mtx);
    if (idx >= 0) {
        ubo_keymap_report_sample(st.rpc, &mic.pp[idx].arr, mic.ts[idx]);
    }
}

/* Decode an AudioSample (FT_POINTER fields) and feed the speaker. */
static void play_sample(const ubo_client_AudioSample *s, float volume) {
    if (!s || !s->data) {
        return;
    }
    int rate = s->rate ? (int)*s->rate : 16000;
    int channels = s->channels ? (int)*s->channels : 1;
    int width = s->width ? (int)*s->width : 2;
    if (width != 2) {
        ESP_LOGW(TAG, "unsupported audio width %d (bytes)", width);
        return;
    }
    ubo_audio_play(s->data->bytes, s->data->size, rate, channels, width, volume);
}

/* talk_start/stop set a command the dispatch worker acts on, so all RPC stays on
 * one task and start->samples->stop ordering is preserved. */
static volatile int s_talk_cmd; /* 0 none, 1 start, 2 stop */

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

/* ── store stream: [current_view, status_bar, is_blanked] ── */
static void on_store(void *user, const ubo_client_Any *results, size_t count) {
    (void)user;
    if (!st.connected) {
        st.connected = true;
        ubo_lvgl_set_connected(true);
    }
    /* SubscribeStore re-delivers ALL selectors whenever ANY one changes (e.g. a
     * status-bar clock tick re-sends current_view unchanged). Apply each part
     * only when it actually changed, so an unrelated tick can't rebuild and
     * re-animate the menu mid page-transition. The hashes track what's on
     * screen, so they stay correct across reconnects too. */
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
            /* out_stream_id = NULL: the camera viewfinder is deferred on-device. */
            ubo_view_render(results[0].type_url, results[0].value->bytes,
                            results[0].value->size, NULL);
        }
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
    case ubo_client_Event_audio_play_audio_sample_event_tag: {
        const ubo_client_AudioPlayAudioSampleEvent *e =
            ev->event.audio_play_audio_sample_event;
        if (e) {
            play_sample(e->sample, e->volume ? *e->volume : 1.0f);
        }
        break;
    }
    case ubo_client_Event_audio_play_audio_sequence_event_tag: {
        /* TTS stream: a chunk with no sample is a keepalive; play in arrival
         * order (id/index reordering is a deliberate follow-up). */
        const ubo_client_AudioPlayAudioSequenceEvent *e =
            ev->event.audio_play_audio_sequence_event;
        if (e && e->sample) {
            play_sample(e->sample, e->volume ? *e->volume : 1.0f);
        }
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
    ubo_client_AudioPlayAudioSampleEvent apse =
        ubo_client_AudioPlayAudioSampleEvent_init_zero;
    ubo_client_AudioPlayAudioSequenceEvent apsq =
        ubo_client_AudioPlayAudioSequenceEvent_init_zero;
    ubo_client_Event evs[4];
    memset(evs, 0, sizeof(evs));
    evs[0].which_event = ubo_client_Event_application_scroll_event_tag;
    evs[0].event.application_scroll_event = &ase;
    evs[1].which_event = ubo_client_Event_menu_choose_by_index_event_tag;
    evs[1].event.menu_choose_by_index_event = &mce;
    evs[2].which_event = ubo_client_Event_audio_play_audio_sample_event_tag;
    evs[2].event.audio_play_audio_sample_event = &apse;
    evs[3].which_event = ubo_client_Event_audio_play_audio_sequence_event_tag;
    evs[3].event.audio_play_audio_sequence_event = &apsq;

    int delay = RECONNECT_INITIAL_DELAY_MS;
    while (!st.stop) {
        time_t start = time(NULL);
        ubo_rpc_subscribe_event(st.rpc, evs, 4, on_event, NULL, &st.stop);
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
        /* Push-to-talk transitions (kept on this task so all RPC is serialized
         * and start -> samples -> stop stay ordered). */
        const int tc = s_talk_cmd;
        if (tc) {
            s_talk_cmd = 0;
            if (tc == 1) {
                ubo_keymap_assistant_listen(st.rpc, true);
                ubo_audio_mic_start(mic_cb, NULL);
            } else {
                ubo_audio_mic_stop();
                mic_drain(); /* flush a trailing chunk before the stop action */
                ubo_keymap_assistant_listen(st.rpc, false);
            }
        }
        /* Stream a captured mic chunk while a talk session is active. */
        mic_drain();
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

void ubo_client_talk_start(void) {
    s_talk_cmd = 1;
}

void ubo_client_talk_stop(void) {
    s_talk_cmd = 2;
}

void ubo_client_start(const char *web_grpc_url) {
    st.rpc = ubo_rpc_create(web_grpc_url);
    if (!st.rpc) {
        ESP_LOGE(TAG, "rpc create failed (%s)", web_grpc_url);
        return;
    }
    st.keyq = xQueueCreate(QUEUE_CAP, KEY_MAX);
    mic.mtx = xSemaphoreCreateMutex();
    mic.ready = -1;
    xTaskCreate(store_task, "ubo_store", 8192, NULL, 5, NULL);
    xTaskCreate(event_task, "ubo_event", 6144, NULL, 5, NULL);
    xTaskCreate(dispatch_task, "ubo_disp", 4096, NULL, 5, NULL);
    ESP_LOGI(TAG, "client started -> %s", web_grpc_url);
}
