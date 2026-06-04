#include "display/backend.h"

#ifdef UBO_WITH_SH8601

#include "display/backend_sh8601.h"

#include "esp_heap_caps.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "lvgl.h"

/* RGB565 — the panel's pixel size in the draw buffer. */
#define SH8601_BYTES_PER_PX 2
/* Partial draw buffer height as a fraction of the screen (memory-conscious;
 * the C6 has 512KB and no PSRAM). 1/10 screen, double-buffered. */
#define SH8601_BUF_DIVISOR 10

/* Handles supplied by the firmware (board.c) before ubo_lvgl_init(). */
static esp_lcd_panel_handle_t s_panel;
static esp_lcd_panel_io_handle_t s_io;

void ubo_backend_sh8601_set_panel(esp_lcd_panel_handle_t panel,
                                  esp_lcd_panel_io_handle_t io) {
    s_panel = panel;
    s_io = io;
}

/* DMA transfer complete (ISR ctx) -> let LVGL release the buffer. */
static bool on_trans_done(esp_lcd_panel_io_handle_t io,
                          esp_lcd_panel_io_event_data_t *edata,
                          void *user_ctx) {
    (void)io;
    (void)edata;
    lv_display_flush_ready((lv_display_t *)user_ctx);
    return false;
}

static void flush_cb(lv_display_t *disp, const lv_area_t *area,
                     uint8_t *px_map) {
    esp_lcd_panel_handle_t panel = lv_display_get_user_data(disp);
    const int32_t w = area->x2 - area->x1 + 1;
    const int32_t h = area->y2 - area->y1 + 1;
    /* The SH8601 reads RGB565 byte-swapped relative to LVGL's native order. */
    lv_draw_sw_rgb565_swap(px_map, (uint32_t)(w * h));
    /* esp_lcd end coords are exclusive; flush_ready fires from on_trans_done. */
    esp_lcd_panel_draw_bitmap(panel, area->x1, area->y1, area->x2 + 1,
                              area->y2 + 1, px_map);
}

/* SH8601/AMOLED requires 2-pixel-aligned flush windows: round each invalidated
 * area to an even start and odd end on both axes. */
static void rounder_cb(lv_event_t *e) {
    lv_area_t *area = lv_event_get_param(e);
    area->x1 &= ~1;
    area->y1 &= ~1;
    area->x2 |= 1;
    area->y2 |= 1;
}

lv_display_t *ubo_backend_sh8601_create(int32_t width, int32_t height) {
    if (!s_panel || !s_io) {
        LV_LOG_ERROR("sh8601 backend: panel not set (call "
                     "ubo_backend_sh8601_set_panel first)");
        return NULL;
    }

    lv_display_t *disp = lv_display_create(width, height);
    if (!disp) {
        return NULL;
    }
    lv_display_set_user_data(disp, s_panel);
    lv_display_set_flush_cb(disp, flush_cb);
    lv_display_add_event_cb(disp, rounder_cb, LV_EVENT_INVALIDATE_AREA, NULL);

    const size_t buf_bytes =
        (size_t)width * (height / SH8601_BUF_DIVISOR) * SH8601_BYTES_PER_PX;
    void *buf1 = heap_caps_malloc(buf_bytes, MALLOC_CAP_DMA);
    void *buf2 = heap_caps_malloc(buf_bytes, MALLOC_CAP_DMA);
    if (!buf1 || !buf2) {
        LV_LOG_ERROR("sh8601 backend: out of DMA memory for draw buffers");
        return NULL;
    }
    lv_display_set_buffers(disp, buf1, buf2, buf_bytes,
                           LV_DISPLAY_RENDER_MODE_PARTIAL);

    const esp_lcd_panel_io_callbacks_t cbs = {.on_color_trans_done =
                                                  on_trans_done};
    esp_lcd_panel_io_register_event_callbacks(s_io, &cbs, disp);

    return disp;
}

#endif /* UBO_WITH_SH8601 */
