/* Map renderer key names to gRPC actions and dispatch them.
 * C port of the Python keyboard.py build_action() + dispatch. */
#ifndef UBO_KEYMAP_H
#define UBO_KEYMAP_H

#include <stdbool.h>

#include <pb.h> /* pb_bytes_array_t */

#include "ubo_rpc.h"

/* Build the Action for `key` and dispatch it over `rpc`.
 *   UP/DOWN/L1/L2/L3 -> KeypadKeyPressAction
 *   BACK/HOME        -> KeypadKeyReleaseAction
 *   M                -> AudioToggleMuteStatusAction (input device)
 * Returns 0 if dispatched, -1 if the key has no mapping. */
int ubo_keymap_dispatch(ubo_rpc *rpc, const char *key);

/* Dispatch AudioSetVolumeAction for the OUTPUT device. `volume` is 0..1.
 * Returns 0 on success. */
int ubo_keymap_set_volume(ubo_rpc *rpc, float volume);

/* Push-to-talk: dispatch AssistantStart/StopListeningAction (start=true/false).
 * Returns 0 on success. */
int ubo_keymap_assistant_listen(ubo_rpc *rpc, bool start);

/* Stream one captured mic chunk to the core as AudioReportSampleAction.
 * `bytes` is a caller-owned pb_bytes_array_t (size-prefixed 16-bit PCM) that
 * must stay valid for the call; `timestamp` is seconds. Returns 0 on success. */
int ubo_keymap_report_sample(ubo_rpc *rpc, const pb_bytes_array_t *bytes,
                             float timestamp);

#endif /* UBO_KEYMAP_H */
