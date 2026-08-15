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
 * On start, `audio_source` tags the mic session so the core keeps only this
 * client's mic and ignores all others; it must equal the `audio_source` passed
 * to ubo_keymap_report_sample. Ignored on stop (may be NULL). A NULL/empty
 * source means the on-device system mic. Returns 0 on success. */
int ubo_keymap_assistant_listen(ubo_rpc *rpc, bool start,
                                const char *audio_source);

/* Wake word: dispatch AssistantStartListeningAction carrying a
 * WakePhraseTriggerSource, so the core can resolve a turn-completion policy.
 *
 * Kept separate from ubo_keymap_assistant_listen rather than folded into it
 * because the two have genuinely different semantics, not just different
 * arguments: a push-to-talk session ends when the button is released, so it is
 * fine for the core to resolve no policy, whereas a wake-word session has no
 * release and relies entirely on the policy this `source` selects to ever stop.
 *
 * `phrase` is the literal wake phrase the model matched ("Jarvis"), `detector`
 * names the engine ("wakenet"), and `mode` is a ubo_client_WakeMode value
 * (CONVERSATION, QUICK_CHAT, ...). `audio_source` behaves exactly as above.
 * Returns 0 on success. */
int ubo_keymap_assistant_listen_wake(ubo_rpc *rpc, const char *audio_source,
                                     const char *phrase, const char *detector,
                                     int mode);

/* Stream one captured mic chunk to the core as AudioReportSampleAction.
 * `bytes` is a caller-owned pb_bytes_array_t (size-prefixed 16-bit PCM) that
 * must stay valid for the call; `timestamp` is seconds. `audio_source` must
 * match the id given to ubo_keymap_assistant_listen so the core binds this
 * sample to the session (NULL/empty = on-device system mic). Returns 0. */
int ubo_keymap_report_sample(ubo_rpc *rpc, const pb_bytes_array_t *bytes,
                             float timestamp, const char *audio_source);

#endif /* UBO_KEYMAP_H */
