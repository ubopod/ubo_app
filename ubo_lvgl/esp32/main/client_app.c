#include "client_app.h"

#include <string.h>
#include <time.h>

#include "esp_log.h"
#include "esp_mac.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

#include "audio.h"
#include "client_core.h"
#include "keymap.h"
#include "ubo_client.pb.h"
#include "ubo_lvgl.h"
#include "ubo_rpc.h"

static const char *TAG = "ubo_client";

#define KEY_MAX 8
#define QUEUE_CAP 16

/* Stable per-device mic source id, e.g. "esp32:aabbccddeeff" (derived from the
 * WiFi MAC at startup). Tags this client's push-to-talk session so the core
 * binds to our mic and drops every other source, including the core host's
 * on-device system mic (which reports an empty source). Mirrors the web UI's
 * per-client AUDIO_SOURCE; passed to both the start action and every sample. */
static char s_audio_source[24];

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
        ubo_keymap_report_sample(st.rpc, &mic.pp[idx].arr, mic.ts[idx],
                                 s_audio_source);
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

/* ── active frame stream (camera viewfinder / video playback) ──
 * The store task writes the id after each view render; the event task reads it
 * to filter FrameStreamChunkEvents, hence the mutex. */
#define STREAM_ID_MAX 64
static struct {
    char active_stream[STREAM_ID_MAX];
    SemaphoreHandle_t mtx;
} fs;

static void on_stream_id(void *user, const char *stream_id) {
    (void)user;
    xSemaphoreTake(fs.mtx, portMAX_DELAY);
    snprintf(fs.active_stream, sizeof(fs.active_stream), "%s", stream_id);
    xSemaphoreGive(fs.mtx);
}

/* ── store stream: [current_view, status_bar, is_blanked] ── */
static void on_store(void *user, const ubo_client_Any *results, size_t count) {
    (void)user;
    ubo_client_handle_store(results, count, &st.connected, on_stream_id, NULL);
}

static void store_task(void *arg) {
    (void)arg;
    const char *sel[] = {"state.main.current_view", "state.main.status_bar",
                         "state.display.is_blanked"};
    ubo_client_backoff bo;
    ubo_client_backoff_init(&bo);
    while (!st.stop) {
        time_t start = time(NULL);
        ubo_rpc_subscribe_store(st.rpc, sel, 3, on_store, NULL, &st.stop);
        if (st.stop) {
            break;
        }
        st.connected = false;
        vTaskDelay(pdMS_TO_TICKS(
            ubo_client_backoff_step(&bo, time(NULL) - start, true)));
    }
    vTaskDelete(NULL);
}

/* ── event stream: common events + audio playback + low-res frame chunks ── */
static unsigned s_chunk_count; /* heap telemetry cadence */

static void on_event(void *user, const ubo_client_Event *ev) {
    (void)user;
    if (ubo_client_handle_event_common(ev)) {
        return;
    }
    switch (ev->which_event) {
    case ubo_client_Event_frame_stream_chunk_event_tag: {
        const ubo_client_FrameStreamChunkEvent *e =
            ev->event.frame_stream_chunk_event;
        if (!e || !e->stream_id || !e->data) {
            break;
        }
        bool active;
        xSemaphoreTake(fs.mtx, portMAX_DELAY);
        active = fs.active_stream[0] &&
                 strcmp(fs.active_stream, e->stream_id) == 0;
        xSemaphoreGive(fs.mtx);
        if (!active) {
            break;
        }
        const int32_t w = e->width ? (int32_t)*e->width : 0;
        const int32_t h = e->height ? (int32_t)*e->height : 0;
        const int32_t off = e->row_offset ? (int32_t)*e->row_offset : 0;
        ubo_lvgl_update_frame_chunk(e->data->bytes, e->data->size, off, w, h);
        if ((++s_chunk_count % 100) == 0) {
            ESP_LOGD(TAG, "frame chunks=%u free_heap=%lu", s_chunk_count,
                     (unsigned long)esp_get_free_heap_size());
        }
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
        ESP_LOGI(TAG, "rx AudioPlayAudioSequenceEvent: sample=%s id=%s",
                 (e && e->sample) ? "yes" : "no", (e && e->id) ? e->id : "?");
        if (e && e->sample) {
            play_sample(e->sample, e->volume ? *e->volume : 1.0f);
        }
        break;
    }
    case ubo_client_Event_audio_stop_playback_event_tag:
        /* Flush buffered speaker audio (e.g. video playback stopped). */
        ubo_audio_stop_playback();
        break;
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
    /* Subscribed only to ESTABLISH the event stream at connect (StackChangedEvent
     * has server initial state, flushing the response headers immediately so a
     * cold stream never misses a TTS burst). It fires only on navigation, not on
     * every view/status tick, so it doesn't flood the shared subscription queue
     * during a chat reply. Ignored in on_event (default case). */
    ubo_client_StackChangedEvent sce = ubo_client_StackChangedEvent_init_zero;
    /* Low-res frame chunks only — the full-res FrameStreamDataEvent (~173KB
     * at 240x240 RGB888) cannot decode within this board's free heap. */
    ubo_client_FrameStreamChunkEvent fsce =
        ubo_client_FrameStreamChunkEvent_init_zero;
    ubo_client_AudioStopPlaybackEvent aspe =
        ubo_client_AudioStopPlaybackEvent_init_zero;
    ubo_client_Event evs[7];
    memset(evs, 0, sizeof(evs));
    evs[0].which_event = ubo_client_Event_application_scroll_event_tag;
    evs[0].event.application_scroll_event = &ase;
    evs[1].which_event = ubo_client_Event_menu_choose_by_index_event_tag;
    evs[1].event.menu_choose_by_index_event = &mce;
    evs[2].which_event = ubo_client_Event_audio_play_audio_sample_event_tag;
    evs[2].event.audio_play_audio_sample_event = &apse;
    evs[3].which_event = ubo_client_Event_audio_play_audio_sequence_event_tag;
    evs[3].event.audio_play_audio_sequence_event = &apsq;
    evs[4].which_event = ubo_client_Event_stack_changed_event_tag;
    evs[4].event.stack_changed_event = &sce;
    evs[5].which_event = ubo_client_Event_frame_stream_chunk_event_tag;
    evs[5].event.frame_stream_chunk_event = &fsce;
    evs[6].which_event = ubo_client_Event_audio_stop_playback_event_tag;
    evs[6].event.audio_stop_playback_event = &aspe;

    ubo_client_backoff bo;
    ubo_client_backoff_init(&bo);
    while (!st.stop) {
        time_t start = time(NULL);
        ubo_rpc_subscribe_event(st.rpc, evs, 7, on_event, NULL, &st.stop);
        if (st.stop) {
            break;
        }
        vTaskDelay(pdMS_TO_TICKS(
            ubo_client_backoff_step(&bo, time(NULL) - start, false)));
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
                ubo_keymap_assistant_listen(st.rpc, true, s_audio_source);
                ubo_audio_mic_start(mic_cb, NULL);
            } else {
                ubo_audio_mic_stop();
                mic_drain(); /* flush a trailing chunk before the stop action */
                ubo_keymap_assistant_listen(st.rpc, false, NULL);
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
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    snprintf(s_audio_source, sizeof(s_audio_source),
             "esp32:%02x%02x%02x%02x%02x%02x", mac[0], mac[1], mac[2], mac[3],
             mac[4], mac[5]);
    ESP_LOGI(TAG, "mic audio_source=%s", s_audio_source);

    st.rpc = ubo_rpc_create(web_grpc_url);
    if (!st.rpc) {
        ESP_LOGE(TAG, "rpc create failed (%s)", web_grpc_url);
        return;
    }
    st.keyq = xQueueCreate(QUEUE_CAP, KEY_MAX);
    mic.mtx = xSemaphoreCreateMutex();
    mic.ready = -1;
    fs.mtx = xSemaphoreCreateMutex();
    if (!st.keyq || !mic.mtx || !fs.mtx) {
        ESP_LOGE(TAG, "client queue/mutex allocation failed");
        return;
    }
    if (xTaskCreate(store_task, "ubo_store", 8192, NULL, 5, NULL) != pdPASS ||
        xTaskCreate(event_task, "ubo_event", 6144, NULL, 5, NULL) != pdPASS ||
        xTaskCreate(dispatch_task, "ubo_disp", 4096, NULL, 5, NULL) != pdPASS) {
        ESP_LOGE(TAG, "client task creation failed (out of memory?)");
        return;
    }
    ESP_LOGI(TAG, "client started -> %s", web_grpc_url);
}
