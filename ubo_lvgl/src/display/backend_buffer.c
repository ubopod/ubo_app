/**
 * @file backend_buffer.c
 * Offscreen framebuffer backend: renders into a plain RGB565 buffer instead of
 * a panel. Used for headless snapshot verification on machines with no display.
 */
#include "backend.h"

#include <stdlib.h>
#include <string.h>

/* Single-display tool: file-scope state holds the one framebuffer. */
static uint8_t *s_fb;   /* RGB565 little-endian, s_w * s_h * 2 */
static int32_t s_w;
static int32_t s_h;

static void buffer_flush_cb(lv_display_t *disp, const lv_area_t *area,
                            uint8_t *px_map)
{
    const int32_t aw = area->x2 - area->x1 + 1;
    for (int32_t y = area->y1; y <= area->y2; y++) {
        for (int32_t x = area->x1; x <= area->x2; x++) {
            const size_t src = ((size_t)(y - area->y1) * aw + (x - area->x1)) * 2;
            const size_t dst = ((size_t)y * s_w + x) * 2;
            s_fb[dst] = px_map[src];
            s_fb[dst + 1] = px_map[src + 1];
        }
    }
    lv_display_flush_ready(disp);
}

lv_display_t *ubo_backend_buffer_create(int32_t width, int32_t height)
{
    s_w = width;
    s_h = height;
    s_fb = calloc((size_t)width * height, 2);

    /* A full-screen draw buffer keeps flushing trivial. */
    const size_t buf_bytes = (size_t)width * height * 2;
    uint8_t *draw_buf = malloc(buf_bytes);
    if (!s_fb || !draw_buf) {
        free(s_fb);
        free(draw_buf);
        s_fb = NULL;
        return NULL;
    }

    lv_display_t *disp = lv_display_create(width, height);
    lv_display_set_color_format(disp, LV_COLOR_FORMAT_RGB565);
    lv_display_set_buffers(disp, draw_buf, NULL, buf_bytes,
                           LV_DISPLAY_RENDER_MODE_FULL);
    lv_display_set_flush_cb(disp, buffer_flush_cb);
    return disp;
}

const uint8_t *ubo_backend_buffer_data(void)
{
    return s_fb;
}

int32_t ubo_backend_buffer_width(void)
{
    return s_w;
}

int32_t ubo_backend_buffer_height(void)
{
    return s_h;
}
