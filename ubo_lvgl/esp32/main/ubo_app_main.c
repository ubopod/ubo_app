/*
 * Device entry point.
 * Bring up the board (I2C + SH8601 QSPI panel), initialize the shared C renderer
 * on the SH8601 backend, run the LVGL loop on a dedicated task, bring up a
 * transport, then start the web-grpc client so live views from ubo-core render
 * on the panel.
 *
 * Two transports, USB preferred:
 *   - USB: PPP over the USB Serial/JTAG cable (usb_ppp.c) to pppd on the Pi.
 *     Chosen when a USB host is attached (SOF) and the stored preference isn't
 *     "wifi". WiFi is then never initialized at all.
 *   - WiFi: today's path — join a network, or fall back to the captive portal.
 *
 * The USB path never demotes itself to WiFi: it retries forever, so a Pi reboot
 * (pppd gone for ~40s) is ridden out rather than being treated as a dead link.
 * The user moves to WiFi with the on-screen switch, which reboots into it — but
 * that "wifi" preference is one-shot: it is consumed and reset to "usb" at the
 * next boot (see app_main), so USB-PPP is always retried first on every power
 * cycle when a host is present. The client's base URL is fixed at
 * ubo_http_create(); there is no retarget-in-place path.
 */
#include <string.h>

#include "audio.h"
#include "board.h"
#include "client_app.h"
#include "display/backend_sh8601.h"
#include "input.h"
#include "net.h"
#include "provisioning.h"
#include "ubo_lvgl.h"
#include "usb_ppp.h"

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "ubo_app";

/* The LVGL loop is stack-hungry (font rendering); give it a generous stack. */
#define LVGL_TASK_STACK 12288
#define USB_LINK_TASK_STACK 3072
/* Wait between PPP negotiation attempts when the peer isn't answering. */
#define USB_RETRY_DELAY_MS 2000

static void lvgl_task(void *arg) {
    (void)arg;
    ubo_lvgl_run(false); /* blocks: drives lv_timer_handler + flushes */
    vTaskDelete(NULL);
}

#ifdef CONFIG_UBO_USB_PPP_ENABLE
/* Own the PPP link for the lifetime of the boot. The gRPC client is started once,
 * on the first successful negotiation, and its own reconnect backoff
 * (client_core.c) then rides out any later PPP outage — while ppp0 is down its
 * HTTP requests simply fail and it retries, raising the disconnect overlay that
 * carries the "Use WiFi" switch. So there is nothing to tear down and restart
 * here; we only have to keep the link itself coming back. */
static void usb_link_task(void *arg) {
    (void)arg;
    const uint32_t probe_ms = CONFIG_UBO_USB_PPP_PROBE_TIMEOUT_S * 1000;
    bool client_started = false;

    for (;;) {
        if (ubo_usb_ppp_start(probe_ms) == 0) {
            if (!client_started) {
                ESP_LOGI(TAG, "core endpoint (usb): %s",
                         CONFIG_UBO_USB_CORE_GRPC_WEB_URL);
                ubo_client_start(CONFIG_UBO_USB_CORE_GRPC_WEB_URL);
                client_started = true;
            }
            ubo_usb_ppp_wait_link_down();
            ESP_LOGW(TAG, "usb link lost; retrying (no fallback to WiFi)");
        }
        ubo_usb_ppp_stop();
        vTaskDelay(pdMS_TO_TICKS(USB_RETRY_DELAY_MS));
    }
}
#endif

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

    /* 1b. Audio: ES8311 codec on the shared I2C bus + full-duplex I2S (speaker
     * playback + push-to-talk mic). Non-fatal if it fails — the UI still runs. */
    if (ubo_audio_init(i2c) != 0) {
        ESP_LOGW(TAG, "audio init failed; continuing without audio");
    }

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

    /* 4. Transport. NVS + netif + event loop are shared by both; only the WiFi
     * path pays for esp_wifi_init. */
    ubo_net_init_base();

#ifdef CONFIG_UBO_USB_PPP_ENABLE
    /* USB first, unless the user explicitly moved to WiFi last boot. The
     * preference is one-shot: consumed right here, then reset back to "usb" in
     * NVS, so WiFi never becomes sticky across power cycles — only this boot
     * honors the user's on-screen "Use WiFi" tap. host_present() is a cheap
     * gate — a bare charger sends no SOF, so power-only cabling costs nothing
     * and falls straight through to WiFi. */
    const bool wanted_wifi = ubo_net_transport_is_wifi();
    if (wanted_wifi) {
        ubo_net_transport_save(false); /* one-shot: don't let this stick */
    }
    if (!wanted_wifi && ubo_usb_ppp_host_present()) {
        ESP_LOGI(TAG, "usb host detected; bringing up PPP (free heap: %lu bytes)",
                 (unsigned long)esp_get_free_heap_size());
        /* Input first: the "Use WiFi" switch on the disconnect overlay is the
         * only way out if the peer never answers, so touch must be live even
         * while the link is still down. */
        ubo_net_transport_set_active(false);
        ubo_input_start(touch);
        ubo_lvgl_set_transport_switch("Use WiFi");
        xTaskCreate(usb_link_task, "usb_link", USB_LINK_TASK_STACK, NULL, 5, NULL);
        return;
    }
#endif

    /* WiFi: init the stack, then try to join (NVS creds, else Kconfig seed).
     * On success start the live client + input (the input task also handles the
     * BOOT long-press WiFi reset); otherwise bring up the captive portal. */
    ubo_net_wifi_init();

    char ssid[UBO_SSID_MAXLEN] = {0}, pass[UBO_PASS_MAXLEN] = {0};
    const uint32_t timeout_ms = CONFIG_UBO_WIFI_CONNECT_TIMEOUT_S * 1000;
    if (resolve_creds(ssid, pass) && ubo_net_connect(ssid, pass, timeout_ms)) {
        ubo_net_creds_save(ssid, pass); /* persist a working seed/retry */
        /* Core endpoint: provisioned host/port (NVS) wins over the Kconfig URL. */
        char url[128];
        const char *core_url = ubo_net_core_url(url, sizeof(url))
                                   ? url
                                   : CONFIG_UBO_CORE_GRPC_WEB_URL;
        ESP_LOGI(TAG, "core endpoint (wifi): %s (free heap: %lu bytes)", core_url,
                 (unsigned long)esp_get_free_heap_size());
        ubo_client_start(core_url);
        ubo_input_start(touch);
#ifdef CONFIG_UBO_USB_PPP_ENABLE
        /* Always safe to offer: "usb" only means *prefer* USB, so if the cable
         * isn't there on the next boot we simply land back here. */
        ubo_net_transport_set_active(true);
        ubo_lvgl_set_transport_switch("Use USB");
#endif
    } else {
        ESP_LOGW(TAG, "no WiFi: starting captive portal '%s'",
                 CONFIG_UBO_PROV_AP_SSID);
        ubo_lvgl_set_provisioning_status(CONFIG_UBO_PROV_AP_SSID, "192.168.4.1");
        ubo_provisioning_run(); /* blocks; reboots on successful provision */
    }
}
