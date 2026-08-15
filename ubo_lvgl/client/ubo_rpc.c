#include "ubo_rpc.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <pb_decode.h>
#include <pb_encode.h>

#include "client_log.h"
#include "grpc_web_frame.h"
#include "http_transport.h"

struct ubo_rpc {
    ubo_http *http;
};

#define PATH_DISPATCH "/store.v1.StoreService/DispatchAction"
#define PATH_SUBSCRIBE_STORE "/store.v1.StoreService/SubscribeStore"
#define PATH_SUBSCRIBE_EVENT "/store.v1.StoreService/SubscribeEvent"

ubo_rpc *ubo_rpc_create(const char *base_url) {
    ubo_rpc *r = calloc(1, sizeof(*r));
    if (!r) {
        return NULL;
    }
    r->http = ubo_http_create(base_url);
    if (!r->http) {
        free(r);
        return NULL;
    }
    return r;
}

void ubo_rpc_destroy(ubo_rpc *r) {
    if (!r) {
        return;
    }
    ubo_http_destroy(r->http);
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

/* Frame a serialized request body into a single gRPC-Web data frame. */
static uint8_t *frame_request(const pb_msgdesc_t *fields, const void *src,
                              size_t *out_len) {
    size_t body_len = 0;
    uint8_t *body = encode_msg(fields, src, &body_len);
    if (!body) {
        return NULL;
    }
    uint8_t *frame = ubo_grpc_web_encode(body, body_len, out_len);
    free(body);
    return frame;
}

int ubo_rpc_dispatch(ubo_rpc *r, const ubo_client_Action *action) {
    ubo_client_DispatchActionRequest req =
        ubo_client_DispatchActionRequest_init_zero;
    req.action = (ubo_client_Action *)action; /* FT_POINTER field */

    size_t frame_len = 0;
    uint8_t *frame =
        frame_request(ubo_client_DispatchActionRequest_fields, &req, &frame_len);
    if (!frame) {
        return -1;
    }
    long status = 0;
    uint8_t *resp = NULL;
    size_t resp_len = 0;
    int rc = ubo_http_post_unary(r->http, PATH_DISPATCH, frame, frame_len, &resp,
                                 &resp_len, &status);
    free(frame);
    if (getenv("UBO_RPC_DEBUG") && resp) {
        fprintf(stderr, "[dispatch] http=%ld resp_len=%zu trailer=\"", status,
                resp_len);
        for (size_t i = 0; i < resp_len; i++) {
            unsigned char c = resp[i];
            fputc((c >= 32 && c < 127) ? c : '.', stderr);
        }
        fprintf(stderr, "\"\n");
    }
    free(resp);
    return (rc == 0 && status == 200) ? 0 : -1;
}

/* ── streaming decode plumbing ── */
struct store_stream {
    ubo_grpc_web_parser parser;
    ubo_rpc_store_cb cb;
    void *user;
};

static bool store_chunk(void *user, const uint8_t *data, size_t len) {
    struct store_stream *st = user;
    if (!ubo_grpc_web_parser_feed(&st->parser, data, len)) {
        return false; /* OOM or poisoned parser: abort the stream */
    }
    uint8_t flag;
    const uint8_t *pl;
    size_t pl_len;
    while (ubo_grpc_web_parser_next(&st->parser, &flag, &pl, &pl_len)) {
        if (ubo_grpc_web_is_trailer(flag)) {
            continue; /* end-of-stream marker; status handled by caller */
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
    if (ubo_grpc_web_parser_take_dropped(&st->parser)) {
        /* One state update lost; the next one resyncs the whole view. */
        UBO_CLIENT_LOGW("store stream: oversized gRPC-Web frame; discarded");
    }
    if (ubo_grpc_web_parser_bad(&st->parser)) {
        UBO_CLIENT_LOGW("store stream: unrecoverable gRPC-Web framing; aborting");
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
    uint8_t *frame =
        frame_request(ubo_client_SubscribeStoreRequest_fields, &req, &frame_len);
    if (!frame) {
        return -1;
    }
    struct store_stream st = {.cb = on_results, .user = user};
    ubo_grpc_web_parser_init(&st.parser);
    int rc = ubo_http_post_stream(r->http, PATH_SUBSCRIBE_STORE, frame, frame_len,
                                  store_chunk, &st, stop);
    ubo_grpc_web_parser_free(&st.parser);
    free(frame);
    return rc;
}

struct event_stream {
    ubo_grpc_web_parser parser;
    ubo_rpc_event_cb cb;
    void *user;
};

static bool event_chunk(void *user, const uint8_t *data, size_t len) {
    struct event_stream *st = user;
    if (!ubo_grpc_web_parser_feed(&st->parser, data, len)) {
        return false; /* OOM or poisoned parser: abort the stream */
    }
    uint8_t flag;
    const uint8_t *pl;
    size_t pl_len;
    while (ubo_grpc_web_parser_next(&st->parser, &flag, &pl, &pl_len)) {
        if (ubo_grpc_web_is_trailer(flag)) {
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
    if (ubo_grpc_web_parser_take_dropped(&st->parser)) {
        /* One event lost — better than dropping the stream and with it every
         * subsequent event. */
        UBO_CLIENT_LOGW("event stream: oversized gRPC-Web frame; discarded");
    }
    if (ubo_grpc_web_parser_bad(&st->parser)) {
        UBO_CLIENT_LOGW("event stream: unrecoverable gRPC-Web framing; aborting");
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
    uint8_t *frame =
        frame_request(ubo_client_SubscribeEventRequest_fields, &req, &frame_len);
    if (!frame) {
        return -1;
    }
    struct event_stream st = {.cb = on_event, .user = user};
    ubo_grpc_web_parser_init(&st.parser);
    int rc = ubo_http_post_stream(r->http, PATH_SUBSCRIBE_EVENT, frame, frame_len,
                                  event_chunk, &st, stop);
    ubo_grpc_web_parser_free(&st.parser);
    free(frame);
    return rc;
}
