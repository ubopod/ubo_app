/**
 * @file sim_main.c
 * Standalone desktop simulator. Opens a 240x240 SDL window and runs the LVGL
 * loop on the main thread (required by SDL on macOS). Closing the window exits
 * (LV_SDL_DIRECT_EXIT).
 */
#include "ubo_lvgl.h"

int main(void)
{
    ubo_lvgl_config cfg = {
        .backend = UBO_BACKEND_SDL,
        .width = 240,
        .height = 240,
    };
    if (ubo_lvgl_init(&cfg) != 0) {
        return 1;
    }
    ubo_lvgl_run(false); /* blocks on the main thread until the window closes */
    return 0;
}
