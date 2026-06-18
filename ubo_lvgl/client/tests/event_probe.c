/* Live event-subscription probe: subscribes to the exact 4 events the ESP32
 * client does (scroll, menu_choose, audio sample, audio sequence) over the
 * reliable curl transport and prints every event's which_event. Use it to tell
 * whether a curated-proto client receives AudioPlayAudioSequenceEvent (TTS)
 * from a given core — isolating a subscription/proto issue from ESP32 transport.
 *
 * Usage: ubo_client_event_probe [base_url]   (default http://localhost:50052/grpc)
 * Trigger TTS (talk to the assistant) while it runs; watch for "*** SEQUENCE".
 */
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#include "ubo_rpc.h"

static volatile bool g_stop = false;

static void on_event(void *user, const ubo_client_Event *ev) {
    (void)user;
    int w = (int)ev->which_event;
    if (w == ubo_client_Event_audio_play_audio_sequence_event_tag) {
        const ubo_client_AudioPlayAudioSequenceEvent *e =
            ev->event.audio_play_audio_sequence_event;
        printf("EVENT which=%d  *** SEQUENCE/TTS ***  sample=%s id=%s\n", w,
               (e && e->sample) ? "yes" : "no", (e && e->id) ? e->id : "?");
    } else if (w == ubo_client_Event_audio_play_audio_sample_event_tag) {
        printf("EVENT which=%d  (sample/chime)\n", w);
    } else {
        printf("EVENT which=%d\n", w);
    }
    fflush(stdout);
}

int main(int argc, char **argv) {
    const char *url = (argc > 1) ? argv[1] : "http://localhost:50052/grpc";
    ubo_rpc *rpc = ubo_rpc_create(url);
    if (!rpc) {
        fprintf(stderr, "failed to create rpc\n");
        return 2;
    }
    printf("event-probe: subscribing scroll/menu_choose/sample/sequence @ %s\n",
           url);

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

    while (!g_stop) {
        int rc = ubo_rpc_subscribe_event(rpc, evs, 4, on_event, NULL, &g_stop);
        fprintf(stderr, "[subscribe_event returned %d; reconnecting]\n", rc);
        sleep(1);
    }
    ubo_rpc_destroy(rpc);
    return 0;
}
