/*
 * Device entry point.
 * Bring up the board (I2C + SH8601 QSPI panel), initialize the shared C renderer
 * on the SH8601 backend, run the LVGL loop on a dedicated task, join WiFi, then
 * start the web-grpc client so live views from ubo-core render on the panel.
 */
#include "board.h"
#include "client_app.h"
#include "display/backend_sh8601.h"
#include "net.h"
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

void app_main(void) {
    /* 1. Hardware: I2C bus + SH8601 QSPI panel (returns the panel-IO too). */
    i2c_master_bus_handle_t i2c = board_i2c_init();
    esp_lcd_panel_io_handle_t io = NULL;
    esp_lcd_panel_handle_t panel = board_display_init(i2c, &io);

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

    /* 4. Join WiFi, then start the live web-grpc client. */
    if (ubo_net_connect(CONFIG_UBO_WIFI_SSID, CONFIG_UBO_WIFI_PASSWORD)) {
        ubo_client_start(CONFIG_UBO_CORE_GRPC_WEB_URL);
    } else {
        ESP_LOGE(TAG, "wifi connect failed");
    }
}
