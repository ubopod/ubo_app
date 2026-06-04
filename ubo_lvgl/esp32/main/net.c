#include "net.h"

#include <string.h>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "nvs.h"
#include "nvs_flash.h"

static const char *TAG = "ubo_net";

#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAIL_BIT BIT1
#define WIFI_MAX_RETRY 20
#define NVS_NS "ubo_wifi"

static EventGroupHandle_t s_eg;
static int s_retry;
static bool s_paused; /* true => stop the STA auto-reconnect loop */

static void on_event(void *arg, esp_event_base_t base, int32_t id, void *data) {
    (void)arg;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        if (s_paused) {
            return;
        }
        if (s_retry < WIFI_MAX_RETRY) {
            esp_wifi_connect();
            s_retry++;
            ESP_LOGI(TAG, "retry connect (%d)", s_retry);
        } else {
            xEventGroupSetBits(s_eg, WIFI_FAIL_BIT);
        }
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *e = (ip_event_got_ip_t *)data;
        ESP_LOGI(TAG, "got ip " IPSTR, IP2STR(&e->ip_info.ip));
        s_retry = 0;
        xEventGroupSetBits(s_eg, WIFI_CONNECTED_BIT);
    }
}

void ubo_net_init(void) {
    esp_err_t r = nvs_flash_init();
    if (r == ESP_ERR_NVS_NO_FREE_PAGES || r == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        r = nvs_flash_init();
    }
    ESP_ERROR_CHECK(r);

    s_eg = xEventGroupCreate();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    const wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, on_event, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP, on_event, NULL, NULL));
}

bool ubo_net_connect(const char *ssid, const char *pass, uint32_t timeout_ms) {
    s_paused = false;
    s_retry = 0;
    xEventGroupClearBits(s_eg, WIFI_CONNECTED_BIT | WIFI_FAIL_BIT);

    wifi_config_t wc = {0};
    strncpy((char *)wc.sta.ssid, ssid, sizeof(wc.sta.ssid) - 1);
    strncpy((char *)wc.sta.password, pass, sizeof(wc.sta.password) - 1);
    wc.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wc));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_LOGI(TAG, "connecting to SSID '%s' (timeout %ums)", ssid,
             (unsigned)timeout_ms);

    EventBits_t bits =
        xEventGroupWaitBits(s_eg, WIFI_CONNECTED_BIT | WIFI_FAIL_BIT, pdFALSE,
                            pdFALSE, pdMS_TO_TICKS(timeout_ms));
    return (bits & WIFI_CONNECTED_BIT) != 0;
}

void ubo_net_pause(void) {
    s_paused = true;
    esp_wifi_disconnect();
}

bool ubo_net_creds_load(char *ssid, char *pass) {
    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READONLY, &h) != ESP_OK) {
        return false;
    }
    size_t sl = UBO_SSID_MAXLEN, pl = UBO_PASS_MAXLEN;
    ssid[0] = pass[0] = '\0';
    esp_err_t rs = nvs_get_str(h, "ssid", ssid, &sl);
    esp_err_t rp = nvs_get_str(h, "pass", pass, &pl);
    nvs_close(h);
    if (rp != ESP_OK) {
        pass[0] = '\0';
    }
    return rs == ESP_OK && ssid[0] != '\0';
}

void ubo_net_creds_save(const char *ssid, const char *pass) {
    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READWRITE, &h) != ESP_OK) {
        ESP_LOGE(TAG, "creds save: nvs_open failed");
        return;
    }
    ESP_ERROR_CHECK(nvs_set_str(h, "ssid", ssid));
    ESP_ERROR_CHECK(nvs_set_str(h, "pass", pass ? pass : ""));
    ESP_ERROR_CHECK(nvs_commit(h));
    nvs_close(h);
    ESP_LOGI(TAG, "creds saved for SSID '%s'", ssid);
}

void ubo_net_creds_clear(void) {
    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READWRITE, &h) != ESP_OK) {
        return;
    }
    nvs_erase_all(h);
    nvs_commit(h);
    nvs_close(h);
    ESP_LOGI(TAG, "stored creds cleared");
}

void ubo_net_core_save(const char *host, const char *port) {
    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READWRITE, &h) != ESP_OK) {
        ESP_LOGE(TAG, "core save: nvs_open failed");
        return;
    }
    const char *hv = (host && host[0]) ? host : "0.0.0.0";
    const char *pv = (port && port[0]) ? port : "50052";
    ESP_ERROR_CHECK(nvs_set_str(h, "host", hv));
    ESP_ERROR_CHECK(nvs_set_str(h, "port", pv));
    ESP_ERROR_CHECK(nvs_commit(h));
    nvs_close(h);
    ESP_LOGI(TAG, "core endpoint saved: %s:%s", hv, pv);
}

bool ubo_net_core_url(char *out, size_t out_sz) {
    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READONLY, &h) != ESP_OK) {
        return false;
    }
    char host[UBO_HOST_MAXLEN] = {0}, port[UBO_PORT_MAXLEN] = {0};
    size_t hl = sizeof(host), pl = sizeof(port);
    esp_err_t rh = nvs_get_str(h, "host", host, &hl);
    if (nvs_get_str(h, "port", port, &pl) != ESP_OK || port[0] == '\0') {
        strcpy(port, "50052");
    }
    nvs_close(h);
    if (rh != ESP_OK || host[0] == '\0') {
        return false;
    }
    snprintf(out, out_sz, "http://%s:%s/grpc", host, port);
    return true;
}
