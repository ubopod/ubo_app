/*
 * Device entry point.
 * Bring up the board (I2C + SH8601 QSPI panel), initialize the shared C renderer
 * on the SH8601 backend, run the LVGL loop on a dedicated task, join WiFi, then
 * start the web-grpc client so live views from ubo-core render on the panel.
 * If WiFi can't be joined, fall back to the captive-portal provisioning flow.
 */
#include <string.h>

#include "board.h"
#include "client_app.h"
#include "display/backend_sh8601.h"
#include "input.h"
#include "net.h"
#include "provisioning.h"
#include "ubo_lvgl.h"

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "ubo_app";

/* The LVGL loop is stack-hungry (font rendering); give it a generous stack. */
#define LVGL_TASK_STACK 12288

static void lvgl_task(void *arg) {
    (void)arg;
    ubo_lvgl_run(false); /* blocks: drives lv_timer_handler + flushes */
    vTaskDelete(NULL);
}

/* Resolve credentials: NVS first, else the build-time Kconfig seed (unless it's
 * still the "changeme" default). Returns true if we have something to try. */
static bool resolve_creds(char *ssid, char *pass) {
    if (ubo_net_creds_load(ssid, pass)) {
        ESP_LOGI(TAG, "using stored WiFi creds (SSID '%s')", ssid);
        return true;
    }
    if (strcmp(CONFIG_UBO_WIFI_SSID, "changeme") != 0) {
        strncpy(ssid, CONFIG_UBO_WIFI_SSID, UBO_SSID_MAXLEN - 1);
        strncpy(pass, CONFIG_UBO_WIFI_PASSWORD, UBO_PASS_MAXLEN - 1);
        ESP_LOGI(TAG, "using Kconfig seed creds (SSID '%s')", ssid);
        return true;
    }
    return false;
}

void app_main(void) {
    /* 1. Hardware: I2C bus + SH8601 QSPI panel (returns the panel-IO too) + touch. */
    i2c_master_bus_handle_t i2c = board_i2c_init();
    esp_lcd_panel_io_handle_t io = NULL;
    esp_lcd_panel_handle_t panel = board_display_init(i2c, &io);
    esp_lcd_touch_handle_t touch = board_touch_init(i2c);

    /* 2. Renderer: hand the panel to the SH8601 backend, then init LVGL. The
     * renderer shows its splash until the first view arrives from the store. */
    ubo_backend_sh8601_set_panel(panel, io);
    const ubo_lvgl_config cfg = {
        .backend = UBO_BACKEND_SH8601,
        .width = BOARD_LCD_H_RES,
        .height = BOARD_LCD_V_RES,
    };
    if (ubo_lvgl_init(&cfg) != 0) {
        ESP_LOGE(TAG, "renderer init failed");
        return;
    }

    /* 3. Run the LVGL loop. */
    xTaskCreate(lvgl_task, "lvgl", LVGL_TASK_STACK, NULL, 5, NULL);
    ESP_LOGI(TAG, "renderer up; free heap: %lu bytes",
             (unsigned long)esp_get_free_heap_size());

    /* 4. WiFi: init the stack, then try to join (NVS creds, else Kconfig seed).
     * On success start the live client + input (the input task also handles the
     * BOOT long-press WiFi reset); otherwise bring up the captive portal. */
    ubo_net_init();

    char ssid[UBO_SSID_MAXLEN] = {0}, pass[UBO_PASS_MAXLEN] = {0};
    const uint32_t timeout_ms = CONFIG_UBO_WIFI_CONNECT_TIMEOUT_S * 1000;
    if (resolve_creds(ssid, pass) && ubo_net_connect(ssid, pass, timeout_ms)) {
        ubo_net_creds_save(ssid, pass); /* persist a working seed/retry */
        /* Core endpoint: provisioned host/port (NVS) wins over the Kconfig URL. */
        char url[128];
        const char *core_url = ubo_net_core_url(url, sizeof(url))
                                   ? url
                                   : CONFIG_UBO_CORE_GRPC_WEB_URL;
        ESP_LOGI(TAG, "core endpoint: %s", core_url);
        ubo_client_start(core_url);
        ubo_input_start(touch);
    } else {
        ESP_LOGW(TAG, "no WiFi: starting captive portal '%s'",
                 CONFIG_UBO_PROV_AP_SSID);
        ubo_lvgl_set_provisioning_status(CONFIG_UBO_PROV_AP_SSID, "192.168.4.1");
        ubo_provisioning_run(); /* blocks; reboots on successful provision */
    }
}
