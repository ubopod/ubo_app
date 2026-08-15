/* Phase-3 verification: drive the C view translator from LIVE store updates into
 * the offscreen BUFFER backend and snapshot each distinct view type to a BMP.
 * Compare the output to the Python web-grpc client's renders for parity.
 *
 * Usage: ubo_client_render_snapshot [base_url] [out_dir]
 *   writes <out_dir>/cview_<TypeName>.bmp for each view type encountered.
 */

#include <pthread.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "keymap.h"
#include "ubo_lvgl.h"
#include "ubo_rpc.h"
#include "view_translate.h"

static volatile bool g_stop = false;
static const char *g_out_dir = "/tmp";

static const char *type_suffix(const char *type_url) {
    const char *dot = type_url ? strrchr(type_url, '.') : NULL;
    return dot ? dot + 1 : (type_url ? type_url : "");
}

static int g_seq = 0;

static void on_results(void *user, const ubo_client_Any *results, size_t count) {
    (void)user;
    if (count == 0 || !results[0].value) {
        return;
    }
    /* results: [current_view, status_bar] */
    if (count > 1 && results[1].value &&
        strstr(results[1].type_url ? results[1].type_url : "", "StatusBarData")) {
        ubo_view_render_status_bar(results[1].value->bytes,
                                   results[1].value->size);
    }
    const char *name = type_suffix(results[0].type_url);
    ubo_view_render(results[0].type_url, results[0].value->bytes,
                    results[0].value->size, NULL);

    /* Let the slide-in transition settle (the loop thread advances it) before
     * snapshotting, so we capture the final view, not a mid-animation frame. */
    usleep(500000);

    /* Sequence-numbered so every transition is captured (not just per-type). */
    char path[256];
    snprintf(path, sizeof(path), "%s/cview_%02d_%s.bmp", g_out_dir, g_seq++, name);
    if (ubo_lvgl_snapshot(path) == 0) {
        printf("snapshot %s\n", path);
        fflush(stdout);
    }
}

struct sub_args {
    ubo_rpc *rpc;
};

static void *sub_thread(void *arg) {
    struct sub_args *a = arg;
    const char *selectors[] = {"state.main.current_view", "state.main.status_bar"};
    ubo_rpc_subscribe_store(a->rpc, selectors, 2, on_results, NULL, &g_stop);
    return NULL;
}

static void key_press(ubo_rpc *rpc, ubo_client_Key key) {
    ubo_client_Key pressed[1] = {key};
    ubo_client_KeypadKeyPressAction kp =
        ubo_client_KeypadKeyPressAction_init_zero;
    kp.key = &key;
    kp.pressed_keys = pressed;
    kp.pressed_keys_count = 1;
    ubo_client_Action act = ubo_client_Action_init_zero;
    act.which_action = ubo_client_Action_keypad_key_press_action_tag;
    act.action.keypad_key_press_action = &kp;
    ubo_rpc_dispatch(rpc, &act);
}

static void key_release(ubo_rpc *rpc, ubo_client_Key key) {
    ubo_client_KeypadKeyReleaseAction kr =
        ubo_client_KeypadKeyReleaseAction_init_zero;
    kr.key = &key;
    ubo_client_Action act = ubo_client_Action_init_zero;
    act.which_action = ubo_client_Action_keypad_key_release_action_tag;
    act.action.keypad_key_release_action = &kr;
    ubo_rpc_dispatch(rpc, &act);
}

int main(int argc, char **argv) {
    const char *url = (argc > 1) ? argv[1] : "http://localhost:50052/grpc";
    if (argc > 2) {
        g_out_dir = argv[2];
    }

    /* Panel size is configurable so the same harness can preview the ESP32-C6
     * 368x448 layout (UBO_SIM_W/H); defaults to the 240x240 Pi panel. NB: to
     * match the device the renderer must also be COMPILED with the matching
     * UBO_W/UBO_H geometry (-DUBO_W=368 ...). */
    const char *sw = getenv("UBO_SIM_W"), *sh = getenv("UBO_SIM_H");
    ubo_lvgl_config cfg = {.backend = UBO_BACKEND_BUFFER,
                           .width = sw ? atoi(sw) : 240,
                           .height = sh ? atoi(sh) : 240};
    if (ubo_lvgl_init(&cfg) != 0) {
        fprintf(stderr, "lvgl init failed\n");
        return 2;
    }

    ubo_rpc *rpc = ubo_rpc_create(url);
    if (!rpc) {
        fprintf(stderr, "rpc create failed\n");
        return 2;
    }

    /* Run the LVGL loop on its own thread so slide transitions actually advance
     * (the snapshot then captures the settled view). */
    ubo_lvgl_run(true);

    struct sub_args a = {rpc};
    pthread_t t;
    pthread_create(&t, NULL, sub_thread, &a);

    /* Navigation: a comma-separated key sequence in UBO_SIM_KEYS drives the core
     * so any screen can be captured (e.g. "HOME,L1,DOWN,L2"). UP/DOWN/L1/L2/L3
     * are presses; BACK/HOME are releases. Defaults to a small tour. */
    const char *keys = getenv("UBO_SIM_KEYS");
    char buf[256];
    snprintf(buf, sizeof(buf), "%s", keys && keys[0] ? keys : "HOME,L1,DOWN,L2,HOME");
    sleep(2);
    for (char *tok = strtok(buf, ","); tok; tok = strtok(NULL, ",")) {
        ubo_client_Key k;
        bool press = true, ok = true;
        if (!strcmp(tok, "UP")) k = ubo_client_Key_KEY_UP;
        else if (!strcmp(tok, "DOWN")) k = ubo_client_Key_KEY_DOWN;
        else if (!strcmp(tok, "L1")) k = ubo_client_Key_KEY_L1;
        else if (!strcmp(tok, "L2")) k = ubo_client_Key_KEY_L2;
        else if (!strcmp(tok, "L3")) k = ubo_client_Key_KEY_L3;
        else if (!strcmp(tok, "BACK")) { k = ubo_client_Key_KEY_BACK; press = false; }
        else if (!strcmp(tok, "HOME")) { k = ubo_client_Key_KEY_HOME; press = false; }
        else if (!strcmp(tok, "M")) { ubo_keymap_dispatch(rpc, "M"); sleep(2); continue; }
        else ok = false;
        if (ok) {
            /* Matches the reference client: UP/DOWN/L1/L2/L3 are press-only;
             * BACK/HOME are release. */
            if (press) key_press(rpc, k);
            else key_release(rpc, k);
        }
        sleep(2);
    }

    g_stop = true;
    pthread_join(t, NULL);
    ubo_rpc_destroy(rpc);
    ubo_lvgl_shutdown();
    printf("done\n");
    return 0;
}
