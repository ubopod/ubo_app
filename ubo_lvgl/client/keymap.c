#include "keymap.h"

#include <string.h>

#include "ubo_client.pb.h"

static bool key_enum(const char *k, ubo_client_Key *out) {
    if (strcmp(k, "UP") == 0) {
        *out = ubo_client_Key_KEY_UP;
    } else if (strcmp(k, "DOWN") == 0) {
        *out = ubo_client_Key_KEY_DOWN;
    } else if (strcmp(k, "L1") == 0) {
        *out = ubo_client_Key_KEY_L1;
    } else if (strcmp(k, "L2") == 0) {
        *out = ubo_client_Key_KEY_L2;
    } else if (strcmp(k, "L3") == 0) {
        *out = ubo_client_Key_KEY_L3;
    } else if (strcmp(k, "BACK") == 0) {
        *out = ubo_client_Key_KEY_BACK;
    } else if (strcmp(k, "HOME") == 0) {
        *out = ubo_client_Key_KEY_HOME;
    } else {
        return false;
    }
    return true;
}

/* UP/DOWN/L1/L2/L3 are press actions; BACK/HOME are release actions. */
static bool is_press_key(const char *k) {
    return strcmp(k, "UP") == 0 || strcmp(k, "DOWN") == 0 ||
           strcmp(k, "L1") == 0 || strcmp(k, "L2") == 0 || strcmp(k, "L3") == 0;
}

int ubo_keymap_dispatch(ubo_rpc *rpc, const char *key) {
    if (strcmp(key, "M") == 0) {
        ubo_client_AudioDevice dev = ubo_client_AudioDevice_AUDIO_DEVICE_INPUT;
        ubo_client_AudioToggleMuteStatusAction mute =
            ubo_client_AudioToggleMuteStatusAction_init_zero;
        mute.device = &dev;
        ubo_client_Action act = ubo_client_Action_init_zero;
        act.which_action = ubo_client_Action_audio_toggle_mute_status_action_tag;
        act.action.audio_toggle_mute_status_action = &mute;
        return ubo_rpc_dispatch(rpc, &act);
    }

    ubo_client_Key k;
    if (!key_enum(key, &k)) {
        return -1;
    }
    ubo_client_Action act = ubo_client_Action_init_zero;
    if (is_press_key(key)) {
        ubo_client_Key pressed[1] = {k};
        ubo_client_KeypadKeyPressAction kp =
            ubo_client_KeypadKeyPressAction_init_zero;
        kp.key = &k;
        kp.pressed_keys = pressed;
        kp.pressed_keys_count = 1;
        act.which_action = ubo_client_Action_keypad_key_press_action_tag;
        act.action.keypad_key_press_action = &kp;
        return ubo_rpc_dispatch(rpc, &act);
    }
    ubo_client_KeypadKeyReleaseAction kr =
        ubo_client_KeypadKeyReleaseAction_init_zero;
    kr.key = &k;
    act.which_action = ubo_client_Action_keypad_key_release_action_tag;
    act.action.keypad_key_release_action = &kr;
    return ubo_rpc_dispatch(rpc, &act);
}

int ubo_keymap_set_volume(ubo_rpc *rpc, float volume) {
    float v = volume;
    ubo_client_AudioDevice dev = ubo_client_AudioDevice_AUDIO_DEVICE_OUTPUT;
    ubo_client_AudioSetVolumeAction sv =
        ubo_client_AudioSetVolumeAction_init_zero;
    sv.volume = &v;
    sv.device = &dev;
    ubo_client_Action act = ubo_client_Action_init_zero;
    act.which_action = ubo_client_Action_audio_set_volume_action_tag;
    act.action.audio_set_volume_action = &sv;
    return ubo_rpc_dispatch(rpc, &act);
}
