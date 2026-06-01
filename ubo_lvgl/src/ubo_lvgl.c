/**
 * @file ubo_lvgl.c
 * Core of libubo_lvgl: init, display-backend selection, the LVGL loop, and the
 * public render entry points.
 *
 * Threading: a single pthread mutex (g_lock) serializes all LVGL access. The
 * loop thread takes it around lv_timer_handler(); the public render functions
 * take it around widget building. This lets the Python bridge (or, in phase 2,
 * a C gRPC decoder) call the render functions from a different thread.
 */
#include "ubo_lvgl.h"

#include <pthread.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "lvgl.h"

#include "display/backend.h"
#include "views/ubo_views.h"

/* ------------------------------------------------------------------------- */
/* Renderer singleton state                                                  */
/* ------------------------------------------------------------------------- */

enum { K_NONE = 0, K_HOME, K_MENU, K_OTHER };

typedef struct {
    bool inited;
    lv_display_t *disp;
    pthread_mutex_t lock;
    pthread_t thread;
    bool threaded;
    volatile bool stop;
    ubo_input_cb input_cb;
    void *input_user;
    /* Transition tracking (previous view). */
    int prev_kind;
    int prev_depth;
    int prev_page;
} ubo_state_t;

static ubo_state_t g = {0};

/* ------------------------------------------------------------------------- */
/* Tick source (monotonic milliseconds)                                      */
/* ------------------------------------------------------------------------- */

static uint32_t ubo_tick_cb(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint32_t)(ts.tv_sec * 1000u + ts.tv_nsec / 1000000u);
}

/* ------------------------------------------------------------------------- */
/* Lock helpers (also exported for view modules, declared in ubo_internal.h) */
/* ------------------------------------------------------------------------- */

void ubo_lock(void)
{
    pthread_mutex_lock(&g.lock);
}

void ubo_unlock(void)
{
    pthread_mutex_unlock(&g.lock);
}

void ubo_emit_input(const char *key, bool pressed)
{
    if (g.input_cb) {
        g.input_cb(key, pressed, g.input_user);
    }
}

/* ------------------------------------------------------------------------- */
/* Init                                                                      */
/* ------------------------------------------------------------------------- */

int ubo_lvgl_init(const ubo_lvgl_config *cfg)
{
    if (g.inited) {
        return 0;
    }

    pthread_mutex_init(&g.lock, NULL);

    lv_init();
    lv_tick_set_cb(ubo_tick_cb);

    const int32_t w = (cfg && cfg->width > 0) ? cfg->width : 240;
    const int32_t h = (cfg && cfg->height > 0) ? cfg->height : 240;
    const ubo_backend_t backend = cfg ? cfg->backend : UBO_BACKEND_SDL;

    lv_display_t *disp = NULL;
    switch (backend) {
        case UBO_BACKEND_SDL:
#ifdef UBO_WITH_SDL
            disp = ubo_backend_sdl_create(w, h);
#else
            LV_LOG_ERROR("SDL backend not compiled in");
#endif
            break;
        case UBO_BACKEND_ST7789:
#ifdef UBO_WITH_ST7789
            disp = ubo_backend_st7789_create(w, h);
#else
            LV_LOG_ERROR("ST7789 backend not compiled in");
#endif
            break;
        case UBO_BACKEND_BUFFER:
            disp = ubo_backend_buffer_create(w, h);
            break;
    }

    if (!disp) {
        LV_LOG_ERROR("display creation failed");
        return -1;
    }
    g.disp = disp;

    /* Load full-coverage icon fonts (falls back to the compiled subset). */
    ubo_fonts_load(getenv("UBO_LVGL_ASSETS_DIR"));

    /* Build the persistent header/content/footer chrome, then show the splash
     * until the first view arrives. */
    ubo_screen_ensure();
    ubo_overlay_splash_show();

    g.inited = true;
    return 0;
}

void ubo_lvgl_set_input_cb(ubo_input_cb cb, void *user)
{
    g.input_cb = cb;
    g.input_user = user;
}

/* ------------------------------------------------------------------------- */
/* Render entry points                                                       */
/* ------------------------------------------------------------------------- */

/* Compute the slide direction from the previous view and start the animation.
 * push/enter -> from right; pop/home -> from left; page down/up -> from
 * bottom/top. */
static void apply_transition(int kind, int depth, int page)
{
    int dx = 0;
    int dy = 0;
    if (g.prev_kind != K_NONE) {
        if (kind == K_HOME && g.prev_kind != K_HOME) {
            dx = -UBO_W;
        } else if (kind == K_MENU) {
            if (g.prev_kind != K_MENU || depth > g.prev_depth) {
                dx = UBO_W;
            } else if (depth < g.prev_depth) {
                dx = -UBO_W;
            } else if (page > g.prev_page) {
                dy = UBO_CONTENT_H;
            } else if (page < g.prev_page) {
                dy = -UBO_CONTENT_H;
            }
        } else if (kind == K_OTHER && g.prev_kind != K_OTHER) {
            dx = UBO_W;
        }
    }
    g.prev_kind = kind;
    g.prev_depth = depth;
    g.prev_page = page;
    ubo_screen_transition(dx, dy);
}

void ubo_lvgl_render_home(const ubo_home_view *v)
{
    if (!v) {
        return;
    }
    ubo_lock();
    ubo_overlay_splash_hide();
    ubo_build_home(v);
    apply_transition(K_HOME, 0, 0);
    ubo_unlock();
}

void ubo_lvgl_render_menu(const ubo_menu_view *v)
{
    if (!v) {
        return;
    }
    ubo_lock();
    ubo_overlay_splash_hide();
    ubo_build_menu(v);
    apply_transition(K_MENU, v->stack_depth, v->page_index);
    ubo_unlock();
}

void ubo_lvgl_render_notification(const ubo_notification_view *v)
{
    if (!v) {
        return;
    }
    ubo_lock();
    ubo_overlay_splash_hide();
    ubo_build_notification(v);
    apply_transition(K_OTHER, 0, 0);
    ubo_unlock();
}

void ubo_lvgl_render_instruction(const ubo_instruction_view *v)
{
    if (!v) {
        return;
    }
    ubo_lock();
    ubo_overlay_splash_hide();
    ubo_build_instruction(v);
    apply_transition(K_OTHER, 0, 0);
    ubo_unlock();
}

void ubo_lvgl_render_prompt(const ubo_prompt_view *v)
{
    if (!v) {
        return;
    }
    ubo_lock();
    ubo_overlay_splash_hide();
    ubo_build_prompt(v);
    apply_transition(K_OTHER, 0, 0);
    ubo_unlock();
}

void ubo_lvgl_render_application(const ubo_application_view *v)
{
    if (!v) {
        return;
    }
    ubo_lock();
    ubo_overlay_splash_hide();
    ubo_build_application(v);
    apply_transition(K_OTHER, 0, 0);
    ubo_unlock();
}

void ubo_lvgl_set_status_bar(const ubo_status_bar *s)
{
    if (!s) {
        return;
    }
    ubo_lock();
    ubo_status_bar_apply(s);
    ubo_unlock();
}

void ubo_lvgl_set_blanked(bool blanked)
{
    ubo_lock();
    ubo_overlay_blank(blanked);
    ubo_unlock();
}

void ubo_lvgl_set_connected(bool connected)
{
    ubo_lock();
    ubo_overlay_disconnected(!connected);
    ubo_unlock();
}

/* ------------------------------------------------------------------------- */
/* Loop                                                                      */
/* ------------------------------------------------------------------------- */

static void *ubo_loop(void *arg)
{
    (void)arg;
    while (!g.stop) {
        ubo_lock();
        uint32_t next_ms = lv_timer_handler();
        ubo_unlock();

        if (next_ms == LV_NO_TIMER_READY || next_ms > 16) {
            next_ms = 16; /* keep animations/SDL responsive */
        }
        struct timespec ts = {.tv_sec = 0, .tv_nsec = (long)next_ms * 1000000L};
        nanosleep(&ts, NULL);
    }
    return NULL;
}

int ubo_lvgl_run(bool threaded)
{
    if (!g.inited) {
        return -1;
    }
    if (threaded) {
        g.threaded = true;
        return pthread_create(&g.thread, NULL, ubo_loop, NULL);
    }
    ubo_loop(NULL);
    return 0;
}

void ubo_lvgl_shutdown(void)
{
    g.stop = true;
    if (g.threaded) {
        pthread_join(g.thread, NULL);
        g.threaded = false;
    }
}

/* ------------------------------------------------------------------------- */
/* Headless snapshot (24-bit BMP from the offscreen RGB565 framebuffer)      */
/* ------------------------------------------------------------------------- */

int ubo_lvgl_get_framebuffer(const uint8_t **data, int32_t *width,
                             int32_t *height)
{
    if (!g.inited) {
        return -1;
    }
    ubo_lock();
    lv_refr_now(g.disp);
    ubo_unlock();
    const uint8_t *fb = ubo_backend_buffer_data();
    if (!fb) {
        return -1;
    }
    if (data) {
        *data = fb;
    }
    if (width) {
        *width = ubo_backend_buffer_width();
    }
    if (height) {
        *height = ubo_backend_buffer_height();
    }
    return 0;
}

static void put_u32_le(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)(v);
    p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16);
    p[3] = (uint8_t)(v >> 24);
}

int ubo_lvgl_snapshot(const char *path)
{
    if (!g.inited) {
        return -1;
    }

    /* Force a full redraw so the framebuffer reflects the current screen. */
    ubo_lock();
    lv_refr_now(g.disp);
    ubo_unlock();

    const uint8_t *fb = ubo_backend_buffer_data();
    const int32_t w = ubo_backend_buffer_width();
    const int32_t h = ubo_backend_buffer_height();
    if (!fb || w <= 0 || h <= 0) {
        LV_LOG_ERROR("snapshot requires UBO_BACKEND_BUFFER");
        return -1;
    }

    const int32_t row_bytes = (w * 3 + 3) & ~3; /* padded to 4 */
    const uint32_t pixels_size = (uint32_t)row_bytes * h;
    const uint32_t offset = 54;

    uint8_t header[54] = {0};
    header[0] = 'B';
    header[1] = 'M';
    put_u32_le(header + 2, offset + pixels_size);
    put_u32_le(header + 10, offset);
    put_u32_le(header + 14, 40);
    put_u32_le(header + 18, (uint32_t)w);
    put_u32_le(header + 22, (uint32_t)h);
    header[26] = 1;  /* planes */
    header[28] = 24; /* bpp */
    put_u32_le(header + 34, pixels_size);

    FILE *f = fopen(path, "wb");
    if (!f) {
        return -1;
    }
    fwrite(header, 1, sizeof(header), f);

    uint8_t *row = malloc((size_t)row_bytes);
    if (!row) {
        fclose(f);
        return -1;
    }
    /* BMP is bottom-up. Convert RGB565 LE -> BGR888. */
    for (int32_t y = h - 1; y >= 0; y--) {
        memset(row, 0, (size_t)row_bytes);
        for (int32_t x = 0; x < w; x++) {
            const size_t i = ((size_t)y * w + x) * 2;
            const uint16_t v = (uint16_t)(fb[i] | (fb[i + 1] << 8));
            const uint8_t r5 = (v >> 11) & 0x1F;
            const uint8_t g6 = (v >> 5) & 0x3F;
            const uint8_t b5 = v & 0x1F;
            row[x * 3 + 0] = (uint8_t)((b5 << 3) | (b5 >> 2));
            row[x * 3 + 1] = (uint8_t)((g6 << 2) | (g6 >> 4));
            row[x * 3 + 2] = (uint8_t)((r5 << 3) | (r5 >> 2));
        }
        fwrite(row, 1, (size_t)row_bytes, f);
    }
    free(row);
    fclose(f);
    return 0;
}
