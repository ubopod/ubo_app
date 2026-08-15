/* Unit tests for the chunked low-res frame path (FrameStreamChunkEvent):
 * 1. nanopb encode/decode round-trip of the curated Event oneof member,
 *    proving the field numbers and pointer-mode structs line up.
 * 2. Headless row-blit + upscale: feed a synthetic 120x120 frame through
 *    ubo_lvgl_update_frame_chunk in whole-row chunks into the BUFFER backend
 *    and assert the expected RGB565 pixels land in the framebuffer.
 * Minimal assert harness: exits non-zero on any failure. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <pb_decode.h>
#include <pb_encode.h>

#include "ubo_client.pb.h"
#include "ubo_lvgl.h"

static int failures = 0;

#define CHECK(cond)                                                            \
    do {                                                                       \
        if (!(cond)) {                                                         \
            printf("FAIL %s:%d: %s\n", __func__, __LINE__, #cond);             \
            failures++;                                                        \
        }                                                                      \
    } while (0)

static void test_event_roundtrip(void) {
    int64_t w = 120, h = 120, off = 30;
    pb_bytes_array_t *payload = malloc(PB_BYTES_ARRAY_T_ALLOCSIZE(6));
    payload->size = 6;
    memcpy(payload->bytes, "\x01\x02\x03\x04\x05\x06", 6);

    char sid[] = "camera:viewfinder";
    ubo_client_FrameStreamChunkEvent ev =
        ubo_client_FrameStreamChunkEvent_init_zero;
    ev.stream_id = sid;
    ev.data = payload;
    ev.width = &w;
    ev.height = &h;
    ev.row_offset = &off;

    ubo_client_Event event = ubo_client_Event_init_zero;
    event.which_event = ubo_client_Event_frame_stream_chunk_event_tag;
    event.event.frame_stream_chunk_event = &ev;

    uint8_t buf[256];
    pb_ostream_t os = pb_ostream_from_buffer(buf, sizeof(buf));
    CHECK(pb_encode(&os, ubo_client_Event_fields, &event));

    ubo_client_Event dec = ubo_client_Event_init_zero;
    pb_istream_t is = pb_istream_from_buffer(buf, os.bytes_written);
    CHECK(pb_decode(&is, ubo_client_Event_fields, &dec));
    CHECK(dec.which_event == ubo_client_Event_frame_stream_chunk_event_tag);
    ubo_client_FrameStreamChunkEvent *d = dec.event.frame_stream_chunk_event;
    CHECK(d != NULL);
    if (d) {
        CHECK(d->stream_id && strcmp(d->stream_id, "camera:viewfinder") == 0);
        CHECK(d->data && d->data->size == 6 && d->data->bytes[5] == 6);
        CHECK(d->width && *d->width == 120);
        CHECK(d->height && *d->height == 120);
        CHECK(d->row_offset && *d->row_offset == 30);
    }
    pb_release(ubo_client_Event_fields, &dec);
    free(payload);
}

static int count_px(const uint8_t *fb, int32_t w, int32_t h, uint16_t v) {
    int n = 0;
    for (int32_t i = 0; i < w * h; i++) {
        uint16_t px = (uint16_t)(fb[i * 2] | (fb[i * 2 + 1] << 8));
        if (px == v) {
            n++;
        }
    }
    return n;
}

static void test_chunk_blit(void) {
    ubo_lvgl_config cfg = {
        .backend = UBO_BACKEND_BUFFER, .width = 240, .height = 240};
    CHECK(ubo_lvgl_init(&cfg) == 0);

    const ubo_render_view v = {.show_status_bar = false,
                               .kind = "frame_stream",
                               .title = "",
                               .stream_id = "test"};
    ubo_lvgl_render_render(&v);

    /* 120x120 frame, top half red / bottom half blue, in 4 x 30-row chunks
     * (7200 bytes each, mirroring the core's <=8KB chunking). */
    enum { W = 120, H = 120, ROWS = 30 };
    static uint8_t chunk[ROWS * W * 2];
    for (int c = 0; c < H / ROWS; c++) {
        const uint16_t color = (c < 2) ? 0xF800 /* red */ : 0x001F /* blue */;
        for (int i = 0; i < ROWS * W; i++) {
            chunk[i * 2] = (uint8_t)(color & 0xFF);
            chunk[i * 2 + 1] = (uint8_t)(color >> 8);
        }
        ubo_lvgl_update_frame_chunk(chunk, sizeof(chunk), c * ROWS, W, H);
    }

    const uint8_t *fb;
    int32_t fw, fh;
    CHECK(ubo_lvgl_get_framebuffer(&fb, &fw, &fh) == 0);
    /* Upscaled 2x => each half covers ~240x120 = 28800 px; allow slack for
     * chrome overlap and edge sampling. */
    int red = count_px(fb, fw, fh, 0xF800);
    int blue = count_px(fb, fw, fh, 0x001F);
    CHECK(red > 10000);
    CHECK(blue > 10000);

    /* Malformed chunks (ragged length, row overflow) are dropped without
     * disturbing the displayed frame. */
    ubo_lvgl_update_frame_chunk(chunk, sizeof(chunk) - 1, 0, W, H);
    ubo_lvgl_update_frame_chunk(chunk, sizeof(chunk), H - ROWS + 1, W, H);
    CHECK(ubo_lvgl_get_framebuffer(&fb, &fw, &fh) == 0);
    CHECK(count_px(fb, fw, fh, 0xF800) == red);
    CHECK(count_px(fb, fw, fh, 0x001F) == blue);

    ubo_lvgl_shutdown();
}

int main(void) {
    test_event_roundtrip();
    test_chunk_blit();
    if (failures) {
        printf("%d failure(s)\n", failures);
        return 1;
    }
    printf("all chunk tests passed\n");
    return 0;
}
