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
#include <string.h>
#include <unistd.h>

#include "ubo_lvgl.h"
#include "ubo_rpc.h"
#include "view_translate.h"

static volatile bool g_stop = false;
static const char *g_out_dir = "/tmp";

static const char *type_suffix(const char *type_url) {
    const char *dot = type_url ? strrchr(type_url, '.') : NULL;
    return dot ? dot + 1 : (type_url ? type_url : "");
}

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

    char path[256];
    snprintf(path, sizeof(path), "%s/cview_%s.bmp", g_out_dir, name);
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

    ubo_lvgl_config cfg = {.backend = UBO_BACKEND_BUFFER, .width = 240, .height = 240};
    if (ubo_lvgl_init(&cfg) != 0) {
        fprintf(stderr, "lvgl init failed\n");
        return 2;
    }

    ubo_rpc *rpc = ubo_rpc_create(url);
    if (!rpc) {
        fprintf(stderr, "rpc create failed\n");
        return 2;
    }

    struct sub_args a = {rpc};
    pthread_t t;
    pthread_create(&t, NULL, sub_thread, &a);

    /* Navigate a small tour so several view types get snapshotted. */
    sleep(2);
    key_release(rpc, ubo_client_Key_KEY_HOME); /* Home */
    sleep(2);
    key_press(rpc, ubo_client_Key_KEY_L1); /* open main menu */
    sleep(2);
    key_press(rpc, ubo_client_Key_KEY_DOWN); /* move selection */
    sleep(1);
    key_press(rpc, ubo_client_Key_KEY_L2); /* open a submenu */
    sleep(2);
    key_release(rpc, ubo_client_Key_KEY_HOME); /* back home */
    sleep(2);

    g_stop = true;
    pthread_join(t, NULL);
    ubo_rpc_destroy(rpc);
    ubo_lvgl_shutdown();
    printf("done\n");
    return 0;
}
