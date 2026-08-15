/* Phase-2 live probe: exercises the C RPC layer against a running core + Envoy.
 *
 * Subscribes to state.main.current_view on a worker thread (printing each
 * view's Any.type_url), then dispatches L1 (expect a MenuViewData) and BACK
 * (expect HomeViewData) — the C mirror of the earlier Python web-grpc probe.
 *
 * Usage: ubo_client_probe [base_url]   (default http://localhost:50052/grpc)
 */

#include <pthread.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#include "ubo_rpc.h"

static volatile bool g_stop = false;
static int g_menu_seen = 0;
static int g_home_seen = 0;
static int g_updates = 0;

static const char *suffix(const char *type_url) {
    const char *slash = type_url ? strrchr(type_url, '/') : NULL;
    return slash ? slash + 1 : (type_url ? type_url : "(null)");
}

static void on_results(void *user, const ubo_client_Any *results, size_t count) {
    (void)user;
    if (count == 0) {
        return;
    }
    const char *s = suffix(results[0].type_url);
    g_updates++;
    printf("update %d: view -> %s\n", g_updates, s);
    fflush(stdout);
    if (strstr(s, "MenuViewData")) {
        g_menu_seen++;
    }
    if (strstr(s, "HomeViewData")) {
        g_home_seen++;
    }
}

struct sub_args {
    ubo_rpc *rpc;
};

static void *sub_thread(void *arg) {
    struct sub_args *a = arg;
    const char *selectors[] = {"state.main.current_view"};
    int rc = ubo_rpc_subscribe_store(a->rpc, selectors, 1, on_results, NULL,
                                     &g_stop);
    fprintf(stderr, "[sub_thread] subscribe_store returned %d\n", rc);
    return NULL;
}

static void dispatch_key_press(ubo_rpc *rpc, ubo_client_Key key) {
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

static void dispatch_key_release(ubo_rpc *rpc, ubo_client_Key key) {
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
    ubo_rpc *rpc = ubo_rpc_create(url);
    if (!rpc) {
        fprintf(stderr, "failed to create rpc\n");
        return 2;
    }
    printf("probing %s\n", url);

    struct sub_args a = {rpc};
    pthread_t t;
    pthread_create(&t, NULL, sub_thread, &a);

    sleep(2);
    printf("--- dispatch HOME (reset) ---\n");
    dispatch_key_release(rpc, ubo_client_Key_KEY_HOME);
    sleep(2);
    int home_before = g_home_seen;
    int menu_before = g_menu_seen;
    printf("--- dispatch L1 (open menu) ---\n");
    dispatch_key_press(rpc, ubo_client_Key_KEY_L1);
    sleep(2);
    printf("--- dispatch BACK (to home) ---\n");
    dispatch_key_release(rpc, ubo_client_Key_KEY_BACK);
    sleep(2);

    g_stop = true;
    pthread_join(t, NULL);
    ubo_rpc_destroy(rpc);

    /* Conclusive: a Menu update must arrive AFTER the L1 dispatch, and a Home
     * update after the BACK dispatch — i.e. dispatch actually drove the stream. */
    bool menu_after_l1 = g_menu_seen > menu_before;
    bool home_after_back = g_home_seen > home_before;
    printf("updates=%d home=%d menu=%d (menu_after_l1=%d home_after_back=%d)\n",
           g_updates, g_home_seen, g_menu_seen, menu_after_l1, home_after_back);
    if (menu_after_l1 && home_after_back) {
        printf("PROBE OK: dispatch drove view changes over web-grpc\n");
        return 0;
    }
    fprintf(stderr, "PROBE FAIL: expected Menu-after-L1 and Home-after-BACK\n");
    return 1;
}
