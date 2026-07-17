#include "usb_ppp.h"

#include "sdkconfig.h"

/* The default build profile has no lwIP PPP stack (ESP_NETIF_DEFAULT_PPP() is
 * itself compiled out), and UBO_USB_PPP_ENABLE depends on LWIP_PPP_SUPPORT, so
 * this whole module reduces to nothing there. Nothing calls into it either —
 * ubo_app_main.c guards the USB path on the same symbol. */
#ifdef CONFIG_UBO_USB_PPP_ENABLE

#include <stdlib.h>

#include "driver/usb_serial_jtag.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_netif_ppp.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"

static const char *TAG = "ubo_usb_ppp";

/* The USJ driver defaults to 256B buffers, which is far too small for
 * TCP-sized PPP frames (MRU 1500 + HDLC escaping). */
#define USJ_TX_BUF 2048
#define USJ_RX_BUF 2048

#define RX_CHUNK 1024
#define RX_READ_TIMEOUT_MS 100
#define RX_TASK_STACK 3072

#define PPP_UP_BIT BIT0
#define PPP_DOWN_BIT BIT1

/* esp_netif driver handle. The base struct must come first: esp_netif_attach()
 * reads `post_attach` through this pointer. */
typedef struct {
    esp_netif_driver_base_t base;
} usj_driver_t;

static struct {
    esp_netif_t *netif;
    usj_driver_t driver;
    EventGroupHandle_t eg;
    volatile bool rx_running;
    /* True between action_start and action_stop. Gates both the RX pump and the
     * link-state callbacks, so bytes and PPP errors belonging to a session we
     * have already torn down can't leak into the next one. */
    volatile bool started;
    bool driver_installed;
} s;

/* ------------------------------------------------------------------------- */
/* esp_netif <-> USB Serial/JTAG glue                                        */
/* ------------------------------------------------------------------------- */

static esp_err_t usj_transmit(void *h, void *buffer, size_t len) {
    (void)h;
    const int written =
        usb_serial_jtag_write_bytes(buffer, len, pdMS_TO_TICKS(100));
    return written == (int)len ? ESP_OK : ESP_FAIL;
}

static esp_err_t usj_post_attach(esp_netif_t *netif, esp_netif_iodriver_handle h) {
    usj_driver_t *drv = h;
    drv->base.netif = netif;
    const esp_netif_driver_ifconfig_t ifconfig = {
        .handle = drv,
        .transmit = usj_transmit,
    };
    return esp_netif_set_driver_config(netif, &ifconfig);
}

/* Pump bytes off the USJ endpoint into lwIP's PPP input. */
static void rx_task(void *arg) {
    (void)arg;
    uint8_t *buf = malloc(RX_CHUNK);
    if (!buf) {
        ESP_LOGE(TAG, "rx buffer alloc failed");
        s.rx_running = false;
        vTaskDelete(NULL);
        return;
    }
    while (s.rx_running) {
        const int n = usb_serial_jtag_read_bytes(buf, RX_CHUNK,
                                                 pdMS_TO_TICKS(RX_READ_TIMEOUT_MS));
        /* Drop anything that arrives while the link is torn down — feeding a
         * stopped PPP netif is not something lwIP expects, and between sessions
         * the peer's pppd is often still spraying LCP requests at us. */
        if (n > 0 && s.started) {
            esp_netif_receive(s.netif, buf, (size_t)n, NULL);
        }
    }
    free(buf);
    vTaskDelete(NULL);
}

/* ------------------------------------------------------------------------- */
/* Link state                                                                */
/* ------------------------------------------------------------------------- */

/* Only meaningful for the session that is currently up: ubo_usb_ppp_stop() clears
 * `started` before closing the link precisely so the PPPERR_USER it provokes
 * doesn't land here and set DOWN on the *next* session, which would make the
 * following ubo_usb_ppp_start() return failure immediately and spin the retry
 * loop. */
static void set_down(void) {
    if (!s.started) {
        return;
    }
    xEventGroupClearBits(s.eg, PPP_UP_BIT);
    xEventGroupSetBits(s.eg, PPP_DOWN_BIT);
}

static void on_ip_event(void *arg, esp_event_base_t base, int32_t id, void *data) {
    (void)arg;
    (void)base;
    if (id == IP_EVENT_PPP_GOT_IP) {
        if (!s.started) {
            return;
        }
        const ip_event_got_ip_t *e = data;
        ESP_LOGI(TAG, "link up: ip " IPSTR " gw " IPSTR, IP2STR(&e->ip_info.ip),
                 IP2STR(&e->ip_info.gw));
        xEventGroupClearBits(s.eg, PPP_DOWN_BIT);
        xEventGroupSetBits(s.eg, PPP_UP_BIT);
    } else if (id == IP_EVENT_PPP_LOST_IP) {
        ESP_LOGW(TAG, "link down: lost IP");
        set_down();
    }
}

static void on_ppp_status(void *arg, esp_event_base_t base, int32_t id, void *data) {
    (void)arg;
    (void)base;
    (void)data;
    /* ERRORNONE is posted on a successful connect; ERRORUSER is the echo of our
     * own ppp_close() from ubo_usb_ppp_stop(). Neither is a link failure. */
    if (id == NETIF_PPP_ERRORNONE || id == NETIF_PPP_ERRORUSER) {
        return;
    }
    /* A dead peer (PPPERR_PEERDEAD — LCP echo failure, e.g. the Pi rebooted or
     * pppd was killed) surfaces *only* here; it never posts IP_EVENT_PPP_LOST_IP.
     * So both this handler and on_ip_event() must feed the DOWN bit, or a link
     * that dies without a clean hangup goes unnoticed.
     *
     * The NETIF_PPP_PHASE_* events are deliberately not used: they only exist
     * when CONFIG_LWIP_PPP_NOTIFY_PHASE_SUPPORT=y (default n), so they would
     * silently never fire. */
    ESP_LOGW(TAG, "link down: ppp error %d", (int)id);
    set_down();
}

/* ------------------------------------------------------------------------- */
/* Public API                                                                */
/* ------------------------------------------------------------------------- */

bool ubo_usb_ppp_host_present(void) {
    /* Referencing this symbol is also what pulls the USJ connection-monitor
     * object (and its tick hook) into the link: ESP-IDF only force-links it via
     * `-u` when the USJ console is enabled, which the .ppp profile turns off. */
    return usb_serial_jtag_is_connected();
}

/* One-time setup, done on the first start(). Each step is separately guarded so
 * a failure partway through can be retried by the next start() without leaking
 * the event group or double-installing the USJ driver. */
static int lazy_init(void) {
    if (s.netif) {
        return 0;
    }

    if (!s.eg) {
        s.eg = xEventGroupCreate();
        if (!s.eg) {
            ESP_LOGE(TAG, "event group alloc failed");
            return -1;
        }
    }

    if (!s.driver_installed) {
        const usb_serial_jtag_driver_config_t usj = {
            .tx_buffer_size = USJ_TX_BUF,
            .rx_buffer_size = USJ_RX_BUF,
        };
        const esp_err_t err = usb_serial_jtag_driver_install(
            (usb_serial_jtag_driver_config_t *)&usj);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "usj driver install failed: %s", esp_err_to_name(err));
            return -1;
        }
        s.driver_installed = true;
    }

    const esp_netif_config_t cfg = ESP_NETIF_DEFAULT_PPP();
    esp_netif_t *netif = esp_netif_new(&cfg);
    if (!netif) {
        ESP_LOGE(TAG, "ppp netif creation failed");
        return -1;
    }

    s.driver.base.post_attach = usj_post_attach;
    ESP_ERROR_CHECK(esp_netif_attach(netif, &s.driver));

    /* Without this, PPPERR_* (including a dead peer) is never posted. */
    esp_netif_ppp_config_t ppp_cfg;
    ESP_ERROR_CHECK(esp_netif_ppp_get_params(netif, &ppp_cfg));
    ppp_cfg.ppp_error_event_enabled = true;
    ESP_ERROR_CHECK(esp_netif_ppp_set_params(netif, &ppp_cfg));

    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, ESP_EVENT_ANY_ID,
                                               on_ip_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(NETIF_PPP_STATUS, ESP_EVENT_ANY_ID,
                                               on_ppp_status, NULL));

    s.rx_running = true;
    if (xTaskCreate(rx_task, "usb_ppp_rx", RX_TASK_STACK, NULL, 5, NULL) != pdPASS) {
        ESP_LOGE(TAG, "rx task creation failed");
        s.rx_running = false;
        esp_event_handler_unregister(IP_EVENT, ESP_EVENT_ANY_ID, on_ip_event);
        esp_event_handler_unregister(NETIF_PPP_STATUS, ESP_EVENT_ANY_ID,
                                     on_ppp_status);
        esp_netif_destroy(netif);
        return -1;
    }

    /* Publish the netif only once everything it depends on exists — the RX task
     * and the callbacks both dereference s.netif. */
    s.netif = netif;
    return 0;
}

int ubo_usb_ppp_start(uint32_t timeout_ms) {
    if (lazy_init() != 0) {
        return -1;
    }

    xEventGroupClearBits(s.eg, PPP_UP_BIT | PPP_DOWN_BIT);
    /* Before action_start: the link-state callbacks and the RX pump gate on it,
     * and LCP/errors can arrive the instant the link starts. */
    s.started = true;
    esp_netif_action_start(s.netif, NULL, 0, NULL); /* kicks LCP */

    ESP_LOGI(TAG, "negotiating (timeout %ums)", (unsigned)timeout_ms);
    const EventBits_t bits =
        xEventGroupWaitBits(s.eg, PPP_UP_BIT | PPP_DOWN_BIT, pdFALSE, pdFALSE,
                            pdMS_TO_TICKS(timeout_ms));
    if (bits & PPP_UP_BIT) {
        return 0;
    }
    ESP_LOGW(TAG, "no PPP peer within %ums (is pppd running on the host?)",
             (unsigned)timeout_ms);
    return -1;
}

void ubo_usb_ppp_stop(void) {
    if (!s.started) {
        return;
    }
    /* Clear `started` first so the PPPERR_USER that action_stop provokes, and any
     * in-flight RX bytes, are ignored rather than marking the *next* session
     * down. */
    s.started = false;
    esp_netif_action_stop(s.netif, NULL, 0, NULL);
}

void ubo_usb_ppp_wait_link_down(void) {
    if (!s.eg) {
        return;
    }
    xEventGroupWaitBits(s.eg, PPP_DOWN_BIT, pdFALSE, pdFALSE, portMAX_DELAY);
}

#endif /* CONFIG_UBO_USB_PPP_ENABLE */
