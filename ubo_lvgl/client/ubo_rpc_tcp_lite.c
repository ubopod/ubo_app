/* tcp-lite RPC layer for the LVGL client.
 *
 * Structural parallel of ubo_rpc.c: same public ubo_rpc.h contract (create /
 * destroy / dispatch / subscribe_store / subscribe_event), same nanopb
 * (de)serialization of the same curated proto types, same blocking/callback
 * semantics — only the wire path differs, swapping gRPC-Web framing + HTTP for
 * tcp-lite framing + a raw socket.
 *
 * DispatchAction opens a fresh connection per call (dispatch_thread /
 * dispatch_task have no reconnect logic; a silently-dead persistent socket
 * would break dispatch forever, so fresh-connect preserves self-healing). The
 * subscribe_* calls connect once and stream until *stop or error, exactly like
 * their gRPC-Web siblings; the reconnect/backoff loop lives in the callers.
 */
#include "ubo_rpc.h"

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include <pb_decode.h>
#include <pb_encode.h>

#include "client_log.h"
#include "tcp_lite_frame.h"
#include "tcp_lite_transport.h"

struct ubo_rpc {
    char *host_port; /* "host:port"; no persistent socket owned here */
};

ubo_rpc *ubo_rpc_create(const char *base_url) {
    ubo_rpc *r = calloc(1, sizeof(*r));
    if (!r) {
        return NULL;
    }
    r->host_port = strdup(base_url);
    if (!r->host_port) {
        free(r);
        return NULL;
    }
    return r;
}

void ubo_rpc_destroy(ubo_rpc *r) {
    if (!r) {
        return;
    }
    free(r->host_port);
    free(r);
}

/* Serialize a nanopb message to a malloc'd buffer. */
static uint8_t *encode_msg(const pb_msgdesc_t *fields, const void *src,
                           size_t *out_len) {
    size_t sz = 0;
    if (!pb_get_encoded_size(&sz, fields, src)) {
        return NULL;
    }
    uint8_t *buf = malloc(sz ? sz : 1);
    if (!buf) {
        return NULL;
    }
    pb_ostream_t os = pb_ostream_from_buffer(buf, sz);
    if (!pb_encode(&os, fields, src)) {
        free(buf);
        return NULL;
    }
    *out_len = os.bytes_written;
    return buf;
}

/* Frame a serialized request body into a single tcp-lite frame. */
static uint8_t *frame_request(uint8_t message_type, const pb_msgdesc_t *fields,
                              const void *src, size_t *out_len) {
    size_t body_len = 0;
    uint8_t *body = encode_msg(fields, src, &body_len);
    if (!body) {
        return NULL;
    }
    uint8_t *frame = ubo_tcp_lite_encode(message_type, body, body_len, out_len);
    free(body);
    return frame;
}

/* ── Dispatch (unary; fresh connection per call) ── */
struct dispatch_ctx {
    ubo_tcp_lite_parser parser;
    bool got_response;
    bool ok;
};

static bool dispatch_chunk(void *user, const uint8_t *data, size_t len) {
    struct dispatch_ctx *dc = user;
    if (!ubo_tcp_lite_parser_feed(&dc->parser, data, len)) {
        return false; /* OOM or poisoned parser: abort */
    }
    uint8_t type;
    const uint8_t *pl;
    size_t pl_len;
    if (ubo_tcp_lite_parser_next(&dc->parser, &type, &pl, &pl_len)) {
        dc->got_response = true;
        if (type == UBO_TCP_LITE_MSG_DISPATCH_ACTION_RESPONSE) {
            ubo_client_DispatchActionResponse resp =
                ubo_client_DispatchActionResponse_init_zero;
            pb_istream_t is = pb_istream_from_buffer(pl, pl_len);
            if (pb_decode(&is, ubo_client_DispatchActionResponse_fields, &resp)) {
                dc->ok = true;
            } else {
                UBO_CLIENT_LOGW(
                    "pb_decode failed: DispatchActionResponse (err=%s frame=%u)",
                    PB_GET_ERROR(&is), (unsigned)pl_len);
            }
            pb_release(ubo_client_DispatchActionResponse_fields, &resp);
        } else {
            UBO_CLIENT_LOGW("dispatch: unexpected message_type 0x%02x",
                            (unsigned)type);
        }
        return false; /* first complete frame is the whole reply; stop */
    }
    if (ubo_tcp_lite_parser_bad(&dc->parser)) {
        return false;
    }
    return true; /* need more bytes */
}

int ubo_rpc_dispatch(ubo_rpc *r, const ubo_client_Action *action) {
    ubo_client_DispatchActionRequest req =
        ubo_client_DispatchActionRequest_init_zero;
    req.action = (ubo_client_Action *)action; /* FT_POINTER field */

    size_t frame_len = 0;
    uint8_t *frame = frame_request(UBO_TCP_LITE_MSG_DISPATCH_ACTION_REQUEST,
                                   ubo_client_DispatchActionRequest_fields, &req,
                                   &frame_len);
    if (!frame) {
        return -1;
    }
    ubo_tcp_lite *t = ubo_tcp_lite_connect(r->host_port);
    if (!t) {
        free(frame);
        return -1;
    }
    struct dispatch_ctx dc = {0};
    ubo_tcp_lite_parser_init(&dc.parser);
    int wr = ubo_tcp_lite_write(t, frame, frame_len);
    free(frame);
    if (wr == 0) {
        volatile bool stop = false;
        ubo_tcp_lite_read_loop(t, dispatch_chunk, &dc, &stop);
    }
    ubo_tcp_lite_parser_free(&dc.parser);
    ubo_tcp_lite_close(t);
    return (wr == 0 && dc.got_response && dc.ok) ? 0 : -1;
}

/* ── SubscribeStore (server stream) ── */
struct store_stream {
    ubo_tcp_lite_parser parser;
    ubo_rpc_store_cb cb;
    void *user;
};

static bool store_chunk(void *user, const uint8_t *data, size_t len) {
    struct store_stream *st = user;
    if (!ubo_tcp_lite_parser_feed(&st->parser, data, len)) {
        return false; /* OOM or poisoned parser: abort the stream */
    }
    uint8_t type;
    const uint8_t *pl;
    size_t pl_len;
    while (ubo_tcp_lite_parser_next(&st->parser, &type, &pl, &pl_len)) {
        if (type != UBO_TCP_LITE_MSG_SUBSCRIBE_STORE_RESPONSE) {
            continue;
        }
        ubo_client_SubscribeStoreResponse resp =
            ubo_client_SubscribeStoreResponse_init_zero;
        pb_istream_t is = pb_istream_from_buffer(pl, pl_len);
        if (pb_decode(&is, ubo_client_SubscribeStoreResponse_fields, &resp)) {
            st->cb(st->user, resp.results, resp.results_count);
        } else {
            UBO_CLIENT_LOGW("pb_decode failed: SubscribeStoreResponse");
        }
        pb_release(ubo_client_SubscribeStoreResponse_fields, &resp);
    }
    if (ubo_tcp_lite_parser_take_dropped(&st->parser)) {
        /* One state update lost; the next one resyncs the whole view. */
        UBO_CLIENT_LOGW("store stream: oversized tcp-lite frame; discarded");
    }
    if (ubo_tcp_lite_parser_bad(&st->parser)) {
        UBO_CLIENT_LOGW("store stream: bad tcp-lite frame; aborting");
        return false;
    }
    return true;
}

int ubo_rpc_subscribe_store(ubo_rpc *r, const char *const *selectors,
                            size_t n_selectors, ubo_rpc_store_cb on_results,
                            void *user, volatile bool *stop) {
    ubo_client_SubscribeStoreRequest req =
        ubo_client_SubscribeStoreRequest_init_zero;
    req.selectors = (char **)(uintptr_t)selectors; /* encode-only, not mutated */
    req.selectors_count = (pb_size_t)n_selectors;

    size_t frame_len = 0;
    uint8_t *frame = frame_request(UBO_TCP_LITE_MSG_SUBSCRIBE_STORE_REQUEST,
                                   ubo_client_SubscribeStoreRequest_fields, &req,
                                   &frame_len);
    if (!frame) {
        return -1;
    }
    ubo_tcp_lite *t = ubo_tcp_lite_connect(r->host_port);
    if (!t) {
        free(frame);
        return -1;
    }
    struct store_stream st = {.cb = on_results, .user = user};
    ubo_tcp_lite_parser_init(&st.parser);
    int rc = ubo_tcp_lite_write(t, frame, frame_len);
    free(frame);
    if (rc == 0) {
        rc = ubo_tcp_lite_read_loop(t, store_chunk, &st, stop);
    }
    ubo_tcp_lite_parser_free(&st.parser);
    ubo_tcp_lite_close(t);
    return rc;
}

/* ── SubscribeEvent (server stream) ── */
struct event_stream {
    ubo_tcp_lite_parser parser;
    ubo_rpc_event_cb cb;
    void *user;
};

static bool event_chunk(void *user, const uint8_t *data, size_t len) {
    struct event_stream *st = user;
    if (!ubo_tcp_lite_parser_feed(&st->parser, data, len)) {
        return false; /* OOM or poisoned parser: abort the stream */
    }
    uint8_t type;
    const uint8_t *pl;
    size_t pl_len;
    while (ubo_tcp_lite_parser_next(&st->parser, &type, &pl, &pl_len)) {
        if (type != UBO_TCP_LITE_MSG_SUBSCRIBE_EVENT_RESPONSE) {
            continue;
        }
        ubo_client_SubscribeEventResponse resp =
            ubo_client_SubscribeEventResponse_init_zero;
        pb_istream_t is = pb_istream_from_buffer(pl, pl_len);
        if (pb_decode(&is, ubo_client_SubscribeEventResponse_fields, &resp)) {
            if (resp.event) {
                st->cb(st->user, resp.event);
            }
        } else {
            /* Include the nanopb error and frame size: distinguishes a memory
             * failure ("realloc failed" on a big frame) from tag drift /
             * corruption, which otherwise look identical. */
            UBO_CLIENT_LOGW(
                "pb_decode failed: SubscribeEventResponse (err=%s frame=%u)",
                PB_GET_ERROR(&is), (unsigned)pl_len);
        }
        pb_release(ubo_client_SubscribeEventResponse_fields, &resp);
    }
    if (ubo_tcp_lite_parser_take_dropped(&st->parser)) {
        /* One event lost — better than dropping the stream and with it every
         * subsequent event. */
        UBO_CLIENT_LOGW("event stream: oversized tcp-lite frame; discarded");
    }
    if (ubo_tcp_lite_parser_bad(&st->parser)) {
        UBO_CLIENT_LOGW("event stream: bad tcp-lite frame; aborting");
        return false;
    }
    return true;
}

int ubo_rpc_subscribe_event(ubo_rpc *r, const ubo_client_Event *events,
                            size_t n_events, ubo_rpc_event_cb on_event,
                            void *user, volatile bool *stop) {
    ubo_client_SubscribeEventRequest req =
        ubo_client_SubscribeEventRequest_init_zero;
    req.events = (ubo_client_Event *)events; /* FT_POINTER repeated, encode-only */
    req.events_count = (pb_size_t)n_events;

    size_t frame_len = 0;
    uint8_t *frame = frame_request(UBO_TCP_LITE_MSG_SUBSCRIBE_EVENT_REQUEST,
                                   ubo_client_SubscribeEventRequest_fields, &req,
                                   &frame_len);
    if (!frame) {
        return -1;
    }
    ubo_tcp_lite *t = ubo_tcp_lite_connect(r->host_port);
    if (!t) {
        free(frame);
        return -1;
    }
    struct event_stream st = {.cb = on_event, .user = user};
    ubo_tcp_lite_parser_init(&st.parser);
    int rc = ubo_tcp_lite_write(t, frame, frame_len);
    free(frame);
    if (rc == 0) {
        rc = ubo_tcp_lite_read_loop(t, event_chunk, &st, stop);
    }
    ubo_tcp_lite_parser_free(&st.parser);
    ubo_tcp_lite_close(t);
    return rc;
}
