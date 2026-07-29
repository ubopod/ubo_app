#include "display/backend.h"

#ifdef UBO_WITH_ESP_LCD

#include "display/backend_esp_lcd.h"

#include "esp_heap_caps.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "lvgl.h"

/* RGB565 — the panel's pixel size in the draw buffer. */
#define ESP_LCD_BYTES_PER_PX 2

/* Panel handles + panel-family parameters, supplied by the firmware (board.c)
 * before ubo_lvgl_init(). */
static ubo_backend_esp_lcd_cfg s_cfg;

void ubo_backend_esp_lcd_configure(const ubo_backend_esp_lcd_cfg *cfg) {
    if (cfg) {
        s_cfg = *cfg;
    }
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
    /* esp_lcd SPI panels read RGB565 byte-swapped relative to LVGL's order. */
    if (s_cfg.swap_rgb565) {
        lv_draw_sw_rgb565_swap(px_map, (uint32_t)(w * h));
    }
    /* esp_lcd end coords are exclusive; flush_ready fires from on_trans_done. */
    esp_lcd_panel_draw_bitmap(panel, area->x1, area->y1, area->x2 + 1,
                              area->y2 + 1, px_map);
}

/* Panels that only accept aligned flush windows (the SH8601 AMOLED needs 2px on
 * both axes): round each invalidated area out to the alignment grid. Registered
 * only when align_px > 1. */
static void rounder_cb(lv_event_t *e) {
    lv_area_t *area = lv_event_get_param(e);
    const int32_t mask = (int32_t)s_cfg.align_px - 1;
    area->x1 &= ~mask;
    area->y1 &= ~mask;
    area->x2 |= mask;
    area->y2 |= mask;
}

lv_display_t *ubo_backend_esp_lcd_create(int32_t width, int32_t height) {
    if (!s_cfg.panel || !s_cfg.io) {
        LV_LOG_ERROR("esp_lcd backend: panel not set (call "
                     "ubo_backend_esp_lcd_configure first)");
        return NULL;
    }
    if (s_cfg.buf_divisor == 0) {
        LV_LOG_ERROR("esp_lcd backend: buf_divisor must be >= 1");
        return NULL;
    }

    lv_display_t *disp = lv_display_create(width, height);
    if (!disp) {
        return NULL;
    }
    lv_display_set_user_data(disp, s_cfg.panel);
    lv_display_set_flush_cb(disp, flush_cb);
    if (s_cfg.align_px > 1) {
        lv_display_add_event_cb(disp, rounder_cb, LV_EVENT_INVALIDATE_AREA,
                                NULL);
    }

    const size_t buf_bytes =
        (size_t)width * (height / s_cfg.buf_divisor) * ESP_LCD_BYTES_PER_PX;
    void *buf1 = heap_caps_malloc(buf_bytes, s_cfg.buf_caps);
    void *buf2 = heap_caps_malloc(buf_bytes, s_cfg.buf_caps);
    if (!buf1 || !buf2) {
        LV_LOG_ERROR("esp_lcd backend: out of DMA memory for draw buffers");
        return NULL;
    }
    lv_display_set_buffers(disp, buf1, buf2, buf_bytes,
                           LV_DISPLAY_RENDER_MODE_PARTIAL);

    const esp_lcd_panel_io_callbacks_t cbs = {.on_color_trans_done =
                                                  on_trans_done};
    esp_lcd_panel_io_register_event_callbacks(s_cfg.io, &cbs, disp);

    return disp;
}

#endif /* UBO_WITH_ESP_LCD */
