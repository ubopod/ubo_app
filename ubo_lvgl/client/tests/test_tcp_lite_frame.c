/* Unit tests for the tcp-lite framing codec (mirrors the Python
 * tests/grpc/test_mcu_frame.py). Minimal assert harness: exits non-zero on the
 * first failure. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "tcp_lite_frame.h"

static int failures = 0;

#define CHECK(cond)                                                            \
    do {                                                                       \
        if (!(cond)) {                                                         \
            printf("FAIL %s:%d: %s\n", __func__, __LINE__, #cond);             \
            failures++;                                                        \
        }                                                                      \
    } while (0)

static const uint8_t ALL_MESSAGE_TYPES[] = {
    UBO_TCP_LITE_MSG_DISPATCH_ACTION_REQUEST,
    UBO_TCP_LITE_MSG_DISPATCH_ACTION_RESPONSE,
    UBO_TCP_LITE_MSG_SUBSCRIBE_STORE_REQUEST,
    UBO_TCP_LITE_MSG_SUBSCRIBE_STORE_RESPONSE,
    UBO_TCP_LITE_MSG_SUBSCRIBE_EVENT_REQUEST,
    UBO_TCP_LITE_MSG_SUBSCRIBE_EVENT_RESPONSE,
    UBO_TCP_LITE_MSG_ERROR,
    UBO_TCP_LITE_MSG_PING,
};

/* Encode one frame, feed it to a fresh parser, and assert it yields exactly
 * that single frame with the expected type/payload. */
static void expect_single(uint8_t type, const uint8_t *payload,
                          size_t payload_len) {
    size_t n;
    uint8_t *frame = ubo_tcp_lite_encode(type, payload, payload_len, &n);
    CHECK(frame != NULL);

    ubo_tcp_lite_parser p;
    ubo_tcp_lite_parser_init(&p);
    CHECK(ubo_tcp_lite_parser_feed(&p, frame, n));
    uint8_t got_type;
    const uint8_t *pl;
    size_t pl_len;
    CHECK(ubo_tcp_lite_parser_next(&p, &got_type, &pl, &pl_len));
    CHECK(got_type == type);
    CHECK(pl_len == payload_len);
    CHECK(payload_len == 0 || memcmp(pl, payload, pl_len) == 0);
    CHECK(!ubo_tcp_lite_parser_next(&p, &got_type, &pl, &pl_len));
    CHECK(!ubo_tcp_lite_parser_bad(&p));
    ubo_tcp_lite_parser_free(&p);
    free(frame);
}

/* Roundtrip every message type with a non-empty and an empty payload. */
static void test_encode_roundtrip_all_types(void) {
    const uint8_t payload[] = "hello-mcu-payload";
    size_t payload_len = sizeof(payload) - 1;
    for (size_t i = 0; i < sizeof(ALL_MESSAGE_TYPES); i++) {
        expect_single(ALL_MESSAGE_TYPES[i], payload, payload_len);
        expect_single(ALL_MESSAGE_TYPES[i], (const uint8_t *)"", 0);
    }
}

/* Two frames concatenated in one feed both pop out via repeated _next(). */
static void test_multiple_frames(void) {
    size_t n1, n2;
    uint8_t *f1 = ubo_tcp_lite_encode(UBO_TCP_LITE_MSG_SUBSCRIBE_STORE_RESPONSE,
                                      (const uint8_t *)"one", 3, &n1);
    uint8_t *f2 = ubo_tcp_lite_encode(UBO_TCP_LITE_MSG_SUBSCRIBE_EVENT_RESPONSE,
                                      (const uint8_t *)"two", 3, &n2);
    uint8_t stream[64];
    memcpy(stream, f1, n1);
    memcpy(stream + n1, f2, n2);

    ubo_tcp_lite_parser p;
    ubo_tcp_lite_parser_init(&p);
    CHECK(ubo_tcp_lite_parser_feed(&p, stream, n1 + n2));
    uint8_t type;
    const uint8_t *pl;
    size_t pl_len;
    CHECK(ubo_tcp_lite_parser_next(&p, &type, &pl, &pl_len));
    CHECK(type == UBO_TCP_LITE_MSG_SUBSCRIBE_STORE_RESPONSE);
    CHECK(pl_len == 3 && memcmp(pl, "one", 3) == 0);
    CHECK(ubo_tcp_lite_parser_next(&p, &type, &pl, &pl_len));
    CHECK(type == UBO_TCP_LITE_MSG_SUBSCRIBE_EVENT_RESPONSE);
    CHECK(pl_len == 3 && memcmp(pl, "two", 3) == 0);
    CHECK(!ubo_tcp_lite_parser_next(&p, &type, &pl, &pl_len));
    ubo_tcp_lite_parser_free(&p);
    free(f1);
    free(f2);
}

/* Feed a frame split into two chunks at `split`, asserting it only completes
 * once every byte has arrived. Uses a 200-byte payload so the length is a
 * 2-byte varint (a varint header can split at any byte, unlike grpc-web's
 * fixed 5-byte header). */
static void feed_split_at(const uint8_t *frame, size_t n, size_t split,
                          const uint8_t *payload, size_t payload_len) {
    ubo_tcp_lite_parser p;
    ubo_tcp_lite_parser_init(&p);
    uint8_t type;
    const uint8_t *pl;
    size_t pl_len;
    CHECK(ubo_tcp_lite_parser_feed(&p, frame, split));
    /* An incomplete frame must never yield a result. */
    if (split < n) {
        CHECK(!ubo_tcp_lite_parser_next(&p, &type, &pl, &pl_len));
    }
    CHECK(ubo_tcp_lite_parser_feed(&p, frame + split, n - split));
    CHECK(ubo_tcp_lite_parser_next(&p, &type, &pl, &pl_len));
    CHECK(type == UBO_TCP_LITE_MSG_SUBSCRIBE_EVENT_RESPONSE);
    CHECK(pl_len == payload_len);
    CHECK(memcmp(pl, payload, pl_len) == 0);
    CHECK(!ubo_tcp_lite_parser_next(&p, &type, &pl, &pl_len));
    ubo_tcp_lite_parser_free(&p);
}

static void test_split_at_every_offset(void) {
    uint8_t payload[200];
    for (size_t i = 0; i < sizeof(payload); i++) {
        payload[i] = (uint8_t)(i & 0xFF);
    }
    size_t n;
    uint8_t *frame = ubo_tcp_lite_encode(UBO_TCP_LITE_MSG_SUBSCRIBE_EVENT_RESPONSE,
                                         payload, sizeof(payload), &n);
    CHECK(frame != NULL);
    /* 1 type byte + 2-byte varint (200 => 0xC8 0x01) + 200 payload. */
    CHECK(n == 1 + 2 + sizeof(payload));
    for (size_t split = 0; split <= n; split++) {
        feed_split_at(frame, n, split, payload, sizeof(payload));
    }
    free(frame);
}

/* A declared length above the cap poisons the parser as soon as the length is
 * fully parsed — before any payload arrives — so a hostile length can't grow
 * the buffer unboundedly. */
static void test_oversized_length_poisons_parser(void) {
    /* Hand-build a header: type + varint(MAX_FRAME + 1). */
    size_t huge = (size_t)UBO_TCP_LITE_MAX_FRAME + 1;
    uint8_t header[1 + UBO_TCP_LITE_MAX_VARINT_BYTES];
    header[0] = UBO_TCP_LITE_MSG_SUBSCRIBE_STORE_RESPONSE;
    size_t i = 1;
    size_t v = huge;
    for (;;) {
        uint8_t byte = (uint8_t)(v & 0x7Fu);
        v >>= 7;
        if (v) {
            header[i++] = byte | 0x80u;
        } else {
            header[i++] = byte;
            break;
        }
    }

    ubo_tcp_lite_parser p;
    ubo_tcp_lite_parser_init(&p);
    CHECK(ubo_tcp_lite_parser_feed(&p, header, i));
    CHECK(!ubo_tcp_lite_parser_bad(&p));
    uint8_t type;
    const uint8_t *pl;
    size_t pl_len;
    CHECK(!ubo_tcp_lite_parser_next(&p, &type, &pl, &pl_len));
    CHECK(ubo_tcp_lite_parser_bad(&p));
    /* Poisoned: further feeds/nexts are safe no-ops. */
    uint8_t junk[16] = {0};
    CHECK(!ubo_tcp_lite_parser_feed(&p, junk, sizeof(junk)));
    CHECK(!ubo_tcp_lite_parser_next(&p, &type, &pl, &pl_len));
    CHECK(ubo_tcp_lite_parser_bad(&p));
    ubo_tcp_lite_parser_free(&p);
}

/* A length varint whose continuation bit never terminates within the byte cap
 * poisons the parser (grpc-web's fixed-length header has no equivalent). */
static void test_malformed_varint_poisons_parser(void) {
    /* type + UBO_TCP_LITE_MAX_VARINT_BYTES bytes all with the continuation
     * bit set: no terminating byte within the cap. */
    uint8_t header[1 + UBO_TCP_LITE_MAX_VARINT_BYTES];
    header[0] = UBO_TCP_LITE_MSG_SUBSCRIBE_EVENT_RESPONSE;
    for (size_t i = 0; i < UBO_TCP_LITE_MAX_VARINT_BYTES; i++) {
        header[1 + i] = 0x80u;
    }

    ubo_tcp_lite_parser p;
    ubo_tcp_lite_parser_init(&p);
    CHECK(ubo_tcp_lite_parser_feed(&p, header, sizeof(header)));
    uint8_t type;
    const uint8_t *pl;
    size_t pl_len;
    CHECK(!ubo_tcp_lite_parser_next(&p, &type, &pl, &pl_len));
    CHECK(ubo_tcp_lite_parser_bad(&p));
    /* Once poisoned, further feeds don't crash and _next keeps returning
     * false. */
    uint8_t junk[16] = {0};
    CHECK(!ubo_tcp_lite_parser_feed(&p, junk, sizeof(junk)));
    CHECK(!ubo_tcp_lite_parser_next(&p, &type, &pl, &pl_len));
    ubo_tcp_lite_parser_free(&p);
}

/* Same malformed-varint poison as above, but delivered one byte per feed —
 * the incremental path most likely to regress the "need more data" vs
 * "poison" boundary. Must stay unpoisoned and yield nothing until the byte
 * that finally exceeds the cap arrives. */
static void test_malformed_varint_poisons_across_feeds(void) {
    uint8_t header[1 + UBO_TCP_LITE_MAX_VARINT_BYTES];
    header[0] = UBO_TCP_LITE_MSG_SUBSCRIBE_EVENT_RESPONSE;
    for (size_t i = 0; i < UBO_TCP_LITE_MAX_VARINT_BYTES; i++) {
        header[1 + i] = 0x80u;
    }

    ubo_tcp_lite_parser p;
    ubo_tcp_lite_parser_init(&p);
    uint8_t type;
    const uint8_t *pl;
    size_t pl_len;
    for (size_t i = 0; i < sizeof(header); i++) {
        CHECK(ubo_tcp_lite_parser_feed(&p, header + i, 1));
        if (i < sizeof(header) - 1) {
            CHECK(!ubo_tcp_lite_parser_next(&p, &type, &pl, &pl_len));
            CHECK(!ubo_tcp_lite_parser_bad(&p));
        }
    }
    CHECK(!ubo_tcp_lite_parser_next(&p, &type, &pl, &pl_len));
    CHECK(ubo_tcp_lite_parser_bad(&p));
    ubo_tcp_lite_parser_free(&p);
}

/* A 3-byte varint length (16384, the next boundary past test_split_at_every_offset's
 * 2-byte case) split across every possible feed offset. */
static void test_split_at_every_offset_three_byte_varint(void) {
    uint8_t payload[16384];
    for (size_t i = 0; i < sizeof(payload); i++) {
        payload[i] = (uint8_t)(i & 0xFF);
    }
    size_t n;
    uint8_t *frame = ubo_tcp_lite_encode(UBO_TCP_LITE_MSG_SUBSCRIBE_EVENT_RESPONSE,
                                         payload, sizeof(payload), &n);
    CHECK(frame != NULL);
    /* 1 type byte + 3-byte varint (16384 => 0x80 0x80 0x01) + payload. */
    CHECK(n == 1 + 3 + sizeof(payload));
    /* Every offset would be slow (16388 parser instances); sample the header
     * region exhaustively (where varint-split bugs actually live) plus a
     * handful of payload offsets. */
    for (size_t split = 0; split <= 8; split++) {
        feed_split_at(frame, n, split, payload, sizeof(payload));
    }
    for (size_t split = n - 8; split <= n; split++) {
        feed_split_at(frame, n, split, payload, sizeof(payload));
    }
    free(frame);
}

/* Varint length boundaries (0/127/128/16383/16384) — the same values the
 * Python codec test cross-checks — survive a framing round-trip. */
static void test_varint_length_boundaries(void) {
    const size_t lengths[] = {0, 1, 127, 128, 16383, 16384};
    for (size_t i = 0; i < sizeof(lengths) / sizeof(lengths[0]); i++) {
        size_t len = lengths[i];
        uint8_t *payload = len ? malloc(len) : NULL;
        for (size_t j = 0; j < len; j++) {
            payload[j] = (uint8_t)(j & 0xFF);
        }
        size_t n;
        uint8_t *frame = ubo_tcp_lite_encode(
            UBO_TCP_LITE_MSG_SUBSCRIBE_STORE_RESPONSE, payload, len, &n);
        CHECK(frame != NULL);

        ubo_tcp_lite_parser p;
        ubo_tcp_lite_parser_init(&p);
        CHECK(ubo_tcp_lite_parser_feed(&p, frame, n));
        uint8_t type;
        const uint8_t *pl;
        size_t pl_len;
        CHECK(ubo_tcp_lite_parser_next(&p, &type, &pl, &pl_len));
        CHECK(pl_len == len);
        CHECK(len == 0 || memcmp(pl, payload, len) == 0);
        CHECK(!ubo_tcp_lite_parser_next(&p, &type, &pl, &pl_len));
        ubo_tcp_lite_parser_free(&p);
        free(frame);
        free(payload);
    }
}

int main(void) {
    test_encode_roundtrip_all_types();
    test_multiple_frames();
    test_split_at_every_offset();
    test_oversized_length_poisons_parser();
    test_malformed_varint_poisons_parser();
    test_malformed_varint_poisons_across_feeds();
    test_split_at_every_offset_three_byte_varint();
    test_varint_length_boundaries();
    if (failures) {
        printf("%d check(s) failed\n", failures);
        return 1;
    }
    printf("all tcp-lite frame tests passed\n");
    return 0;
}
