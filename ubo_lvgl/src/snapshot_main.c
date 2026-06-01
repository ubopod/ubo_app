/**
 * @file snapshot_main.c
 * Headless snapshot tool: render a sample view to a BMP with no display.
 * Usage: ubo_lvgl_snapshot <out.bmp> [menu|home]
 *
 * Drives the same public render API the Python bridge will use, so the snapshot
 * exercises the real render path.
 */
#include "ubo_lvgl.h"

#include <stdio.h>
#include <string.h>

static void sample_status_bar(void)
{
    ubo_status_bar sb = {
        .title = "ubo-r",
        .clock = "13:37",
        .has_temperature = true,
        .temperature = 42,
    };
    ubo_lvgl_set_status_bar(&sb);
}

static void render_menu(void)
{
    ubo_menu_item items[] = {
        {.key = "wifi", .label = "WiFi", .icon = "\U000F05A9",
         .is_selected = true, .background_color = "#1a1a1a"},
        {.key = "sound", .label = "Sound", .icon = "\U000F057E",
         .background_color = "#1a1a1a"},
        {.key = "apps", .label = "Apps", .icon = "\U000F0493",
         .background_color = "#1a1a1a"},
        {.key = "settings", .label = "Settings", .icon = "\U000F02DC",
         .background_color = "#1a1a1a"},
    };
    ubo_menu_view v = {
        .show_status_bar = true,
        .title = "Main",
        .items = items,
        .item_count = (int)(sizeof(items) / sizeof(items[0])),
        .page_index = 0,
        .total_pages = 2,
    };
    ubo_lvgl_render_menu(&v);
}

static void render_home(void)
{
    ubo_home_view v = {
        .show_status_bar = true,
        .cpu_percent = 37,
        .ram_percent = 64,
        .volume_level = 0.5,
    };
    ubo_lvgl_render_home(&v);
}

int main(int argc, char **argv)
{
    const char *out = (argc > 1) ? argv[1] : "snapshot.bmp";
    const char *view = (argc > 2) ? argv[2] : "menu";

    ubo_lvgl_config cfg = {
        .backend = UBO_BACKEND_BUFFER,
        .width = 240,
        .height = 240,
    };
    if (ubo_lvgl_init(&cfg) != 0) {
        fprintf(stderr, "init failed\n");
        return 1;
    }

    sample_status_bar();
    if (strcmp(view, "home") == 0) {
        render_home();
    } else if (strcmp(view, "notification") == 0) {
        ubo_notification_view v = {
            .show_status_bar = true,
            .title = "Battery",
            .icon = "\U000F02FC",
            .content = "Battery level is low. Please connect a charger.",
            .color = "#FF9800",
            .total_pages = 1,
        };
        ubo_lvgl_render_notification(&v);
    } else if (strcmp(view, "instruction") == 0) {
        ubo_instruction_view v = {
            .show_status_bar = true,
            .title = "Update",
            .spinner = true,
            .instruction = "Installing update",
            .progress_text = "42%",
            .footer_text = "Do not power off",
        };
        ubo_lvgl_render_instruction(&v);
    } else if (strcmp(view, "prompt") == 0) {
        ubo_menu_item opts[] = {
            {.key = "yes", .label = "Yes"},
            {.key = "no", .label = "No"},
        };
        ubo_prompt_view v = {
            .show_status_bar = true,
            .title = "Confirm",
            .prompt = "Reboot the device now?",
            .items = opts,
            .item_count = 2,
        };
        ubo_lvgl_render_prompt(&v);
    } else if (strcmp(view, "application") == 0) {
        ubo_application_view v = {.show_status_bar = true,
                                  .application_id = "camera"};
        ubo_lvgl_render_application(&v);
    } else if (strcmp(view, "blank") == 0) {
        render_menu();
        ubo_lvgl_set_blanked(true);
    } else if (strcmp(view, "disconnect") == 0) {
        render_menu();
        ubo_lvgl_set_connected(false);
    } else if (strcmp(view, "splash") == 0) {
        /* no render: the splash shown at init stays up */
    } else {
        render_menu();
    }

    if (ubo_lvgl_snapshot(out) != 0) {
        fprintf(stderr, "snapshot failed\n");
        return 1;
    }
    printf("wrote %s (%s)\n", out, view);
    return 0;
}
