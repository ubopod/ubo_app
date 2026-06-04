/* Map renderer key names to gRPC actions and dispatch them.
 * C port of the Python keyboard.py build_action() + dispatch. */
#ifndef UBO_KEYMAP_H
#define UBO_KEYMAP_H

#include "ubo_rpc.h"

/* Build the Action for `key` and dispatch it over `rpc`.
 *   UP/DOWN/L1/L2/L3 -> KeypadKeyPressAction
 *   BACK/HOME        -> KeypadKeyReleaseAction
 *   M                -> AudioToggleMuteStatusAction (input device)
 * Returns 0 if dispatched, -1 if the key has no mapping. */
int ubo_keymap_dispatch(ubo_rpc *rpc, const char *key);

#endif /* UBO_KEYMAP_H */
