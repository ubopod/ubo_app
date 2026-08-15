/**
 * @file backend_sdl.c
 * Desktop development backend: an SDL window via LVGL's built-in SDL driver.
 * LVGL pumps SDL events through its own internal timer, so the loop only needs
 * to call lv_timer_handler().
 */
#include "backend.h"

#ifdef UBO_WITH_SDL

#include <SDL.h>

#include "ubo_internal.h"

/* Map desktop keys to ubo keypad keys (mirrors the Kivy client's keyboard.py).
 * An SDL event watch sees every event regardless of LVGL's own polling. */
static int sdl_key_watch(void *user, SDL_Event *ev)
{
    (void)user;
    if (ev->type != SDL_KEYDOWN && ev->type != SDL_KEYUP) {
        return 0;
    }
    const bool pressed = (ev->type == SDL_KEYDOWN);
    const char *key = NULL;
    switch (ev->key.keysym.sym) {
        case SDLK_UP:
        case SDLK_k:
            key = "UP";
            break;
        case SDLK_DOWN:
        case SDLK_j:
            key = "DOWN";
            break;
        case SDLK_1:
            key = "L1";
            break;
        case SDLK_2:
            key = "L2";
            break;
        case SDLK_3:
            key = "L3";
            break;
        case SDLK_LEFT:
        case SDLK_ESCAPE:
        case SDLK_h:
            key = "BACK";
            break;
        case SDLK_BACKSPACE:
            key = "HOME";
            break;
        case SDLK_m:
            key = "M"; /* toggle microphone mute (mirrors the Kivy client) */
            break;
        default:
            break;
    }
    if (key) {
        ubo_emit_input(key, pressed);
    }
    return 0;
}

lv_display_t *ubo_backend_sdl_create(int32_t width, int32_t height)
{
    lv_display_t *disp = lv_sdl_window_create(width, height);
    if (disp) {
        lv_sdl_window_set_title(disp, "Ubo LVGL");
        SDL_AddEventWatch(sdl_key_watch, NULL);
    }
    return disp;
}

#endif /* UBO_WITH_SDL */
