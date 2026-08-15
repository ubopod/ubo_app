/* Offline layout preview: render representative views straight into the BUFFER
 * backend and snapshot each to a BMP, with no live core. Deterministic content
 * (selected items, icons, headings, long labels) for iterating on geometry /
 * fonts at a given panel size.
 *
 * Usage: ubo_client_layout_preview [out_dir]
 *   UBO_SIM_W / UBO_SIM_H set the panel size (default 240). To match the device
 *   the renderer must also be COMPILED with the matching UBO_W/UBO_H geometry.
 */
#include <stdio.h>
#include <stdlib.h>

#include "ubo_lvgl.h"

static const char *g_dir = "/tmp";

static void snap(const char *name) {
    char path[256];
    snprintf(path, sizeof(path), "%s/preview_%s.bmp", g_dir, name);
    if (ubo_lvgl_snapshot(path) == 0) {
        printf("snapshot %s\n", path);
    }
}

int main(int argc, char **argv) {
    if (argc > 1) {
        g_dir = argv[1];
    }
    const char *sw = getenv("UBO_SIM_W"), *sh = getenv("UBO_SIM_H");
    ubo_lvgl_config cfg = {.backend = UBO_BACKEND_BUFFER,
                           .width = sw ? atoi(sw) : 240,
                           .height = sh ? atoi(sh) : 240};
    if (ubo_lvgl_init(&cfg) != 0) {
        fprintf(stderr, "lvgl init failed\n");
        return 2;
    }

    const ubo_status_bar sb = {
        .title = NULL,
        .clock = "23:09",
        .has_temperature = true,
        .temperature = 21.0,
    };
    ubo_lvgl_set_status_bar(&sb);

    /* 0. Home view: nav strip + CPU/RAM gauges + volume bar. */
    const ubo_menu_item nav[] = {
        {.key = "1", .icon = "\U000F035C", .is_short = true},
        {.key = "2", .icon = "\U000F009A", .is_short = true},
        {.key = "3", .icon = "\U000F0425", .is_short = true},
    };
    const ubo_home_view home = {.show_status_bar = true,
                                .items = nav,
                                .item_count = 3,
                                .cpu_percent = 81,
                                .ram_percent = 77,
                                .volume_level = 0.6};
    ubo_lvgl_render_home(&home);
    snap("home");

    /* 1. Headless menu with icons; middle item selected (checks the selected
     * border + the squared left edge + item proportions). */
    const ubo_menu_item mitems[] = {
        {.key = "1", .label = "Apps", .icon = "\U000F003B"},
        {.key = "2", .label = "Settings", .icon = "\U000F0493", .is_selected = true},
        {.key = "3", .label = "About", .icon = "\U000F02FC"},
    };
    const ubo_menu_view menu = {.show_status_bar = true,
                                .title = "Main",
                                .items = mitems,
                                .item_count = 3,
                                .page_index = 0,
                                .total_pages = 1};
    ubo_lvgl_render_menu(&menu);
    snap("menu_selected");

    /* 2. Headed menu (heading band + one item). */
    const ubo_menu_item hitems[] = {
        {.key = "1", .label = "Wi-Fi", .icon = "\U000F0928"},
    };
    const ubo_menu_view headed = {.show_status_bar = true,
                                  .title = "Settings",
                                  .heading = "Network",
                                  .sub_heading = "connected",
                                  .items = hitems,
                                  .item_count = 1,
                                  .page_index = 0,
                                  .total_pages = 1};
    ubo_lvgl_render_menu(&headed);
    snap("menu_headed");

    /* 3. Notification. */
    const ubo_notification_view notif = {
        .show_status_bar = true,
        .title = "Battery",
        .content = "Battery level is low. Connect a charger soon.",
        .icon = "\U000F0079",
    };
    ubo_lvgl_render_notification(&notif);
    snap("notification");

    /* 4. Prompt. */
    const ubo_menu_item pitems[] = {
        {.key = "1", .label = "Yes", .icon = "\U000F012C"},
        {.key = "2", .label = "No", .icon = "\U000F0156"},
    };
    const ubo_prompt_view prompt = {.show_status_bar = true,
                                    .title = "Confirm",
                                    .prompt = "Reboot the device now?",
                                    .items = pitems,
                                    .item_count = 2};
    ubo_lvgl_render_prompt(&prompt);
    snap("prompt");

    ubo_lvgl_shutdown();
    printf("done\n");
    return 0;
}
