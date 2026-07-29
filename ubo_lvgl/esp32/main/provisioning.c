/*
 * Captive-portal WiFi provisioning: SoftAP + DNS catch-all + HTTP form.
 * Brought up when the device cannot join a stored/seed network within the
 * connect timeout. The user joins the "ubo-setup" AP, the OS captive check is
 * redirected to our page, they pick a scanned SSID + enter a password, and we
 * persist the creds to NVS and reboot onto the real network.
 */
#include "provisioning.h"

#include <stdlib.h>
#include <string.h>

#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "net.h"
#include "sdkconfig.h"

/* dns_server.h references esp_ip4_addr_t, so it must follow esp_netif.h. */
#include "dns_server.h"

static const char *TAG = "ubo_prov";

#define AP_IP "192.168.4.1"
#define MAX_SCAN_AP 16

/* Percent-decode `src` (urlencoded form value) into `dst` (size `dstlen`). */
static void url_decode(char *dst, const char *src, size_t dstlen) {
    size_t o = 0;
    for (size_t i = 0; src[i] && o + 1 < dstlen; i++) {
        if (src[i] == '%' && src[i + 1] && src[i + 2]) {
            char hex[3] = {src[i + 1], src[i + 2], 0};
            dst[o++] = (char)strtol(hex, NULL, 16);
            i += 2;
        } else if (src[i] == '+') {
            dst[o++] = ' ';
        } else {
            dst[o++] = src[i];
        }
    }
    dst[o] = '\0';
}

/* Escape `src` for HTML element content. SSIDs are attacker-controlled radio
 * input (a nearby AP named "</option><script>..." would otherwise inject into
 * the setup page); never emit them into markup raw. */
static void html_escape(char *dst, const char *src, size_t dstlen) {
    size_t o = 0;
    for (size_t i = 0; src[i]; i++) {
        const char *rep = NULL;
        switch (src[i]) {
        case '&': rep = "&amp;"; break;
        case '<': rep = "&lt;"; break;
        case '>': rep = "&gt;"; break;
        case '"': rep = "&quot;"; break;
        case '\'': rep = "&#39;"; break;
        default: break;
        }
        size_t need = rep ? strlen(rep) : 1;
        if (o + need + 1 > dstlen) {
            break;
        }
        if (rep) {
            memcpy(dst + o, rep, need);
            o += need;
        } else {
            dst[o++] = src[i];
        }
    }
    dst[o] = '\0';
}

/* GET /: scan nearby networks and render a form with an SSID dropdown. */
static esp_err_t root_get(httpd_req_t *req) {
    esp_wifi_scan_start(NULL, true); /* blocking scan on the STA interface */
    uint16_t n = 0;
    esp_wifi_scan_get_ap_num(&n);
    if (n > MAX_SCAN_AP) {
        n = MAX_SCAN_AP;
    }
    wifi_ap_record_t *recs = calloc(n ? n : 1, sizeof(*recs));
    if (recs) {
        esp_wifi_scan_get_ap_records(&n, recs);
    } else {
        n = 0;
    }

    httpd_resp_set_type(req, "text/html");
    httpd_resp_sendstr_chunk(
        req,
        "<!DOCTYPE html><html><head><meta charset=utf-8>"
        "<meta name=viewport content=\"width=device-width,initial-scale=1\">"
        "<title>Ubo WiFi setup</title></head><body "
        "style=\"font-family:sans-serif;max-width:480px;margin:24px auto;padding:0 "
        "16px\"><h2>Ubo WiFi setup</h2>"
        "<form method=POST action=/save>"
        "<p><label>Network<br><select name=ssid style=\"width:100%;padding:8px\">");
    for (uint16_t i = 0; i < n; i++) {
        /* Skip empty/hidden SSIDs and obvious duplicates of the previous row. */
        if (recs[i].ssid[0] == '\0') {
            continue;
        }
        if (i > 0 && strcmp((char *)recs[i].ssid, (char *)recs[i - 1].ssid) == 0) {
            continue;
        }
        /* 32-byte SSID, worst case all chars escape to 6 bytes. */
        char ssid_esc[32 * 6 + 1];
        html_escape(ssid_esc, (char *)recs[i].ssid, sizeof(ssid_esc));
        httpd_resp_sendstr_chunk(req, "<option>");
        httpd_resp_sendstr_chunk(req, ssid_esc);
        httpd_resp_sendstr_chunk(req, "</option>");
    }
    httpd_resp_sendstr_chunk(
        req,
        "</select></label></p>"
        "<p><label>Password<br><input type=password name=password "
        "style=\"width:100%;padding:8px\"></label></p>"
        "<p><label>Ubo hostname/IP (optional)<br><input name=host "
        "placeholder=\"e.g. 192.168.1.50\" "
        "style=\"width:100%;padding:8px\"></label></p>"
        /* Pre-filled with this build's transport port: 50054 for tcp-lite
         * (mcu_server.py), 50052 for gRPC-Web via Envoy. */
        "<p><label>Port<br><input name=port value=\"" UBO_DEFAULT_PORT
        "\" inputmode=numeric "
        "style=\"width:100%;padding:8px\"></label></p>"
        "<p><button type=submit style=\"padding:10px 16px\">Connect</button></p>"
        "</form></body></html>");
    httpd_resp_sendstr_chunk(req, NULL); /* end chunked response */
    free(recs);
    return ESP_OK;
}

/* POST /save: persist the submitted creds and reboot onto the new network. */
static esp_err_t save_post(httpd_req_t *req) {
    char body[320];
    int len = httpd_req_recv(req, body, sizeof(body) - 1);
    if (len <= 0) {
        httpd_resp_send_500(req);
        return ESP_FAIL;
    }
    body[len] = '\0';

    char ssid_enc[96] = {0}, pass_enc[160] = {0};
    char host_enc[96] = {0}, port_enc[16] = {0};
    char ssid[UBO_SSID_MAXLEN] = {0}, pass[UBO_PASS_MAXLEN] = {0};
    char host[UBO_HOST_MAXLEN] = {0}, port[UBO_PORT_MAXLEN] = {0};
    httpd_query_key_value(body, "ssid", ssid_enc, sizeof(ssid_enc));
    httpd_query_key_value(body, "password", pass_enc, sizeof(pass_enc));
    httpd_query_key_value(body, "host", host_enc, sizeof(host_enc));
    httpd_query_key_value(body, "port", port_enc, sizeof(port_enc));
    url_decode(ssid, ssid_enc, sizeof(ssid));
    url_decode(pass, pass_enc, sizeof(pass));
    url_decode(host, host_enc, sizeof(host));
    url_decode(port, port_enc, sizeof(port));

    if (ssid[0] == '\0') {
        httpd_resp_set_status(req, "302 Found");
        httpd_resp_set_hdr(req, "Location", "http://" AP_IP "/");
        httpd_resp_send(req, NULL, 0);
        return ESP_OK;
    }

    ubo_net_creds_save(ssid, pass);
    /* empty host -> 0.0.0.0, empty port -> UBO_DEFAULT_PORT */
    ubo_net_core_save(host, port);
    httpd_resp_set_type(req, "text/html");
    httpd_resp_sendstr(req,
                       "<!DOCTYPE html><html><body style=\"font-family:sans-serif\">"
                       "<h2>Saved &mdash; rebooting</h2>"
                       "<p>The device will reconnect to your network.</p>"
                       "</body></html>");
    ESP_LOGI(TAG, "creds submitted; rebooting");
    vTaskDelay(pdMS_TO_TICKS(1500));
    esp_restart();
    return ESP_OK;
}

/* Any other path (incl. OS captive-portal probe URLs) -> redirect to the form
 * so the phone/laptop pops the page automatically. */
static esp_err_t redirect_404(httpd_req_t *req, httpd_err_code_t err) {
    (void)err;
    httpd_resp_set_status(req, "302 Found");
    httpd_resp_set_hdr(req, "Location", "http://" AP_IP "/");
    httpd_resp_send(req, NULL, 0);
    return ESP_OK;
}

static void start_softap(void) {
    esp_netif_create_default_wifi_ap();

    wifi_config_t ap = {0};
    strncpy((char *)ap.ap.ssid, CONFIG_UBO_PROV_AP_SSID, sizeof(ap.ap.ssid) - 1);
    ap.ap.ssid_len = strlen(CONFIG_UBO_PROV_AP_SSID);
    ap.ap.channel = 1;
    ap.ap.max_connection = 4;
    ap.ap.authmode = WIFI_AUTH_OPEN; /* open network for easy provisioning */

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_APSTA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &ap));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_LOGI(TAG, "SoftAP '%s' up at http://%s", CONFIG_UBO_PROV_AP_SSID, AP_IP);
}

static void start_http(void) {
    httpd_handle_t srv = NULL;
    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    cfg.lru_purge_enable = true;
    ESP_ERROR_CHECK(httpd_start(&srv, &cfg));

    const httpd_uri_t root = {.uri = "/", .method = HTTP_GET, .handler = root_get};
    const httpd_uri_t save = {
        .uri = "/save", .method = HTTP_POST, .handler = save_post};
    httpd_register_uri_handler(srv, &root);
    httpd_register_uri_handler(srv, &save);
    httpd_register_err_handler(srv, HTTPD_404_NOT_FOUND, redirect_404);
}

void ubo_provisioning_run(void) {
    /* Quiet the STA auto-reconnect so it doesn't fight the AP-side scan. */
    ubo_net_pause();

    start_softap();

    /* Resolve every DNS query to the AP so the OS captive check hits our page. */
    dns_server_config_t dns = DNS_SERVER_CONFIG_SINGLE("*", "WIFI_AP_DEF");
    start_dns_server(&dns);

    start_http();

    ESP_LOGI(TAG, "captive portal ready; free heap: %lu bytes",
             (unsigned long)esp_get_free_heap_size());

    /* The servers run on their own tasks; block here until the POST handler
     * reboots the device. */
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(10000));
    }
}
