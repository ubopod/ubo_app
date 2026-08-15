/* Unit tests for the gRPC-Web framing codec (mirrors the Python
 * tests/test_grpc_web_frame.py). Minimal assert harness: exits non-zero on the
 * first failure. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "grpc_web_frame.h"

static int failures = 0;

#define CHECK(cond)                                                            \
    do {                                                                       \
        if (!(cond)) {                                                         \
            printf("FAIL %s:%d: %s\n", __func__, __LINE__, #cond);             \
            failures++;                                                        \
        }                                                                      \
    } while (0)

/* Feed `bytes` to a fresh parser and assert it yields exactly the expected
 * single data frame with `payload`. */
static void expect_single(const uint8_t *bytes, size_t n, const char *payload) {
    ubo_grpc_web_parser p;
    ubo_grpc_web_parser_init(&p);
    CHECK(ubo_grpc_web_parser_feed(&p, bytes, n));
    uint8_t flag;
    const uint8_t *pl;
    size_t pl_len;
    CHECK(ubo_grpc_web_parser_next(&p, &flag, &pl, &pl_len));
    CHECK(flag == UBO_GRPC_WEB_DATA_FLAG);
    CHECK(pl_len == strlen(payload));
    CHECK(memcmp(pl, payload, pl_len) == 0);
    CHECK(!ubo_grpc_web_parser_next(&p, &flag, &pl, &pl_len));
    ubo_grpc_web_parser_free(&p);
}

static void test_encode_roundtrip(void) {
    const char *payload = "hello world";
    size_t n;
    uint8_t *frame = ubo_grpc_web_encode((const uint8_t *)payload,
                                         strlen(payload), &n);
    CHECK(frame != NULL);
    CHECK(n == UBO_GRPC_WEB_HEADER_SIZE + strlen(payload));
    expect_single(frame, n, payload);
    free(frame);
}

static void test_encode_empty(void) {
    size_t n;
    uint8_t *frame = ubo_grpc_web_encode((const uint8_t *)"", 0, &n);
    CHECK(frame != NULL);
    CHECK(n == UBO_GRPC_WEB_HEADER_SIZE);
    expect_single(frame, n, "");
    free(frame);
}

static void test_multiple_frames(void) {
    size_t n1, n2;
    uint8_t *f1 = ubo_grpc_web_encode((const uint8_t *)"one", 3, &n1);
    uint8_t *f2 = ubo_grpc_web_encode((const uint8_t *)"two", 3, &n2);
    uint8_t stream[64];
    memcpy(stream, f1, n1);
    memcpy(stream + n1, f2, n2);

    ubo_grpc_web_parser p;
    ubo_grpc_web_parser_init(&p);
    CHECK(ubo_grpc_web_parser_feed(&p, stream, n1 + n2));
    uint8_t flag;
    const uint8_t *pl;
    size_t pl_len;
    CHECK(ubo_grpc_web_parser_next(&p, &flag, &pl, &pl_len));
    CHECK(pl_len == 3 && memcmp(pl, "one", 3) == 0);
    CHECK(ubo_grpc_web_parser_next(&p, &flag, &pl, &pl_len));
    CHECK(pl_len == 3 && memcmp(pl, "two", 3) == 0);
    CHECK(!ubo_grpc_web_parser_next(&p, &flag, &pl, &pl_len));
    ubo_grpc_web_parser_free(&p);
    free(f1);
    free(f2);
}

static void test_split_across_chunks(void) {
    size_t n;
    uint8_t *frame = ubo_grpc_web_encode((const uint8_t *)"abcdef", 6, &n);
    ubo_grpc_web_parser p;
    ubo_grpc_web_parser_init(&p);
    uint8_t flag;
    const uint8_t *pl;
    size_t pl_len;
    /* Split mid-header (2 bytes), then mid-payload, then the rest. */
    CHECK(ubo_grpc_web_parser_feed(&p, frame, 2));
    CHECK(!ubo_grpc_web_parser_next(&p, &flag, &pl, &pl_len));
    CHECK(ubo_grpc_web_parser_feed(&p, frame + 2, 5));
    CHECK(!ubo_grpc_web_parser_next(&p, &flag, &pl, &pl_len));
    CHECK(ubo_grpc_web_parser_feed(&p, frame + 7, n - 7));
    CHECK(ubo_grpc_web_parser_next(&p, &flag, &pl, &pl_len));
    CHECK(pl_len == 6 && memcmp(pl, "abcdef", 6) == 0);
    ubo_grpc_web_parser_free(&p);
    free(frame);
}

static void test_trailer(void) {
    const char *body = "grpc-status:0\r\ngrpc-message:OK\r\n";
    size_t blen = strlen(body);
    uint8_t frame[64];
    frame[0] = UBO_GRPC_WEB_TRAILER_FLAG;
    frame[1] = 0;
    frame[2] = 0;
    frame[3] = (uint8_t)((blen >> 8) & 0xFF);
    frame[4] = (uint8_t)(blen & 0xFF);
    memcpy(frame + 5, body, blen);

    ubo_grpc_web_parser p;
    ubo_grpc_web_parser_init(&p);
    CHECK(ubo_grpc_web_parser_feed(&p, frame, 5 + blen));
    uint8_t flag;
    const uint8_t *pl;
    size_t pl_len;
    CHECK(ubo_grpc_web_parser_next(&p, &flag, &pl, &pl_len));
    CHECK(ubo_grpc_web_is_trailer(flag));
    char msg[32];
    long status = ubo_grpc_web_parse_trailer(pl, pl_len, msg, sizeof(msg));
    CHECK(status == 0);
    CHECK(strcmp(msg, "OK") == 0);
    ubo_grpc_web_parser_free(&p);
}

static void test_trailer_nonzero(void) {
    const char *body = "grpc-status:14\r\ngrpc-message:unavailable\r\n";
    long status = ubo_grpc_web_parse_trailer((const uint8_t *)body, strlen(body),
                                             NULL, 0);
    CHECK(status == 14);
}

static void test_is_trailer(void) {
    CHECK(!ubo_grpc_web_is_trailer(UBO_GRPC_WEB_DATA_FLAG));
    CHECK(ubo_grpc_web_is_trailer(UBO_GRPC_WEB_TRAILER_FLAG));
}

/* A header declaring a payload beyond UBO_GRPC_WEB_MAX_FRAME is discarded, not
 * fatal: the payload never reaches the buffer (so a hostile length can't grow
 * it), the parser stays usable, and the next frame still decodes. Aborting
 * instead would tear down both the store and event streams over one oversized
 * message. */
static void test_oversized_frame_is_skipped(void) {
    uint32_t huge = UBO_GRPC_WEB_MAX_FRAME + 1;
    uint8_t header[UBO_GRPC_WEB_HEADER_SIZE] = {
        UBO_GRPC_WEB_DATA_FLAG,
        (uint8_t)((huge >> 24) & 0xFF),
        (uint8_t)((huge >> 16) & 0xFF),
        (uint8_t)((huge >> 8) & 0xFF),
        (uint8_t)(huge & 0xFF),
    };
    ubo_grpc_web_parser p;
    ubo_grpc_web_parser_init(&p);
    CHECK(ubo_grpc_web_parser_feed(&p, header, sizeof(header)));
    CHECK(!ubo_grpc_web_parser_bad(&p));
    uint8_t flag;
    const uint8_t *pl;
    size_t pl_len;
    CHECK(!ubo_grpc_web_parser_next(&p, &flag, &pl, &pl_len));
    CHECK(!ubo_grpc_web_parser_bad(&p));
    CHECK(ubo_grpc_web_parser_take_dropped(&p));
    CHECK(!ubo_grpc_web_parser_take_dropped(&p)); /* consumed */

    /* Feed the oversized payload in chunks; none of it is buffered. */
    uint8_t chunk[4096] = {0};
    size_t fed = 0;
    while (fed < huge) {
        size_t n = huge - fed < sizeof(chunk) ? huge - fed : sizeof(chunk);
        CHECK(ubo_grpc_web_parser_feed(&p, chunk, n));
        CHECK(!ubo_grpc_web_parser_next(&p, &flag, &pl, &pl_len));
        fed += n;
    }

    /* Resynchronised: the frame after the oversized one decodes normally. */
    const uint8_t body[] = "back-in-sync";
    size_t frame_len = 0;
    uint8_t *frame = ubo_grpc_web_encode(body, sizeof(body) - 1, &frame_len);
    CHECK(frame != NULL);
    CHECK(ubo_grpc_web_parser_feed(&p, frame, frame_len));
    CHECK(ubo_grpc_web_parser_next(&p, &flag, &pl, &pl_len));
    CHECK(flag == UBO_GRPC_WEB_DATA_FLAG);
    CHECK(pl_len == sizeof(body) - 1);
    CHECK(memcmp(pl, body, pl_len) == 0);
    free(frame);
    ubo_grpc_web_parser_free(&p);
}

/* Same stream, but fed at ragged chunk boundaries — including one chunk that
 * straddles the oversized payload's tail and the next frame's header. The skip
 * must end on exactly the right byte or every later frame is misparsed. */
static void test_oversized_frame_skip_boundary(void) {
    uint32_t huge = UBO_GRPC_WEB_MAX_FRAME + 1;
    const uint8_t body[] = "after";
    size_t next_len = 0;
    uint8_t *next = ubo_grpc_web_encode(body, sizeof(body) - 1, &next_len);
    CHECK(next != NULL);

    /* A real stream: [oversized header][huge payload][next frame]. */
    size_t blob_len = UBO_GRPC_WEB_HEADER_SIZE + huge + next_len;
    uint8_t *blob = calloc(1, blob_len);
    CHECK(blob != NULL);
    blob[0] = UBO_GRPC_WEB_DATA_FLAG;
    blob[1] = (uint8_t)((huge >> 24) & 0xFF);
    blob[2] = (uint8_t)((huge >> 16) & 0xFF);
    blob[3] = (uint8_t)((huge >> 8) & 0xFF);
    blob[4] = (uint8_t)(huge & 0xFF);
    memcpy(blob + UBO_GRPC_WEB_HEADER_SIZE + huge, next, next_len);

    ubo_grpc_web_parser p;
    ubo_grpc_web_parser_init(&p);
    uint8_t flag;
    const uint8_t *pl;
    size_t pl_len;
    bool got = false;
    /* 1499 is coprime with the frame sizes, so boundaries land mid-header,
     * mid-payload and across the payload/next-frame seam. */
    for (size_t off = 0; off < blob_len; off += 1499) {
        size_t n = blob_len - off < 1499 ? blob_len - off : 1499;
        CHECK(ubo_grpc_web_parser_feed(&p, blob + off, n));
        while (ubo_grpc_web_parser_next(&p, &flag, &pl, &pl_len)) {
            CHECK(!got); /* the oversized frame is never yielded */
            got = true;
            CHECK(pl_len == sizeof(body) - 1);
            CHECK(memcmp(pl, body, pl_len) == 0);
        }
        CHECK(!ubo_grpc_web_parser_bad(&p));
    }
    CHECK(got);
    CHECK(ubo_grpc_web_parser_take_dropped(&p));
    free(blob);
    free(next);
    ubo_grpc_web_parser_free(&p);
}

/* A payload length exactly at the cap is still accepted. */
static void test_max_frame_boundary_ok(void) {
    uint32_t max = UBO_GRPC_WEB_MAX_FRAME;
    uint8_t header[UBO_GRPC_WEB_HEADER_SIZE] = {
        UBO_GRPC_WEB_DATA_FLAG,
        (uint8_t)((max >> 24) & 0xFF),
        (uint8_t)((max >> 16) & 0xFF),
        (uint8_t)((max >> 8) & 0xFF),
        (uint8_t)(max & 0xFF),
    };
    ubo_grpc_web_parser p;
    ubo_grpc_web_parser_init(&p);
    CHECK(ubo_grpc_web_parser_feed(&p, header, sizeof(header)));
    uint8_t flag;
    const uint8_t *pl;
    size_t pl_len;
    /* Incomplete (payload not fed) but NOT poisoned. */
    CHECK(!ubo_grpc_web_parser_next(&p, &flag, &pl, &pl_len));
    CHECK(!ubo_grpc_web_parser_bad(&p));
    ubo_grpc_web_parser_free(&p);
}

int main(void) {
    test_encode_roundtrip();
    test_encode_empty();
    test_multiple_frames();
    test_split_across_chunks();
    test_trailer();
    test_trailer_nonzero();
    test_is_trailer();
    test_oversized_frame_is_skipped();
    test_oversized_frame_skip_boundary();
    test_max_frame_boundary_ok();
    if (failures) {
        printf("%d check(s) failed\n", failures);
        return 1;
    }
    printf("all frame tests passed\n");
    return 0;
}
