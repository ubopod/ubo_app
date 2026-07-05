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

/* A header declaring a payload beyond UBO_GRPC_WEB_MAX_FRAME poisons the
 * parser immediately (before any payload arrives) and everything after is
 * rejected, so a hostile length can't grow the buffer unboundedly. */
static void test_oversized_frame_poisons_parser(void) {
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
    CHECK(ubo_grpc_web_parser_bad(&p));
    /* Poisoned: further feeds are refused so the buffer can't grow. */
    uint8_t junk[16] = {0};
    CHECK(!ubo_grpc_web_parser_feed(&p, junk, sizeof(junk)));
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
    test_oversized_frame_poisons_parser();
    test_max_frame_boundary_ok();
    if (failures) {
        printf("%d check(s) failed\n", failures);
        return 1;
    }
    printf("all frame tests passed\n");
    return 0;
}
