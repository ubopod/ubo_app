/* gRPC-Web RPC layer for the LVGL client.
 *
 * Composes nanopb (de)serialization, the gRPC-Web framing codec, and the HTTP
 * transport into the three StoreService calls the client uses:
 *   - DispatchAction (unary)         — send an Action
 *   - SubscribeStore (server stream) — current_view / status_bar / is_blanked
 *   - SubscribeEvent (server stream) — menu-choose / app-scroll / frame-stream
 *
 * The subscribe_* calls block until *stop is set or the stream errors; run them
 * on worker threads. Decoded messages handed to callbacks are valid only for
 * the duration of the call (freed with pb_release right after).
 */
#ifndef UBO_RPC_H
#define UBO_RPC_H

#include <stdbool.h>
#include <stddef.h>

#include "ubo_client.pb.h"

typedef struct ubo_rpc ubo_rpc;

ubo_rpc *ubo_rpc_create(const char *base_url);
void ubo_rpc_destroy(ubo_rpc *r);

/* Dispatch an Action (unary, fire-and-forget semantics). Returns 0 on success
 * (HTTP 200), <0 otherwise. */
int ubo_rpc_dispatch(ubo_rpc *r, const ubo_client_Action *action);

/* Subscribe to store selectors. on_results is called for each streamed
 * SubscribeStoreResponse with its decoded Any[] (count entries). Blocks until
 * *stop or error. */
typedef void (*ubo_rpc_store_cb)(void *user, const ubo_client_Any *results,
                                 size_t count);
int ubo_rpc_subscribe_store(ubo_rpc *r, const char *const *selectors,
                            size_t n_selectors, ubo_rpc_store_cb on_results,
                            void *user, volatile bool *stop);

/* Subscribe to events. on_event is called for each streamed Event. Blocks until
 * *stop or error. */
typedef void (*ubo_rpc_event_cb)(void *user, const ubo_client_Event *event);
int ubo_rpc_subscribe_event(ubo_rpc *r, const ubo_client_Event *events,
                            size_t n_events, ubo_rpc_event_cb on_event,
                            void *user, volatile bool *stop);

#endif /* UBO_RPC_H */
