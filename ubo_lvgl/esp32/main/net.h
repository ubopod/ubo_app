/**
 * @file net.h
 * Minimal WiFi station bring-up for the ESP32-C6 (2.4GHz), plus NVS-persisted
 * credentials for the captive-portal provisioning flow.
 */
#ifndef UBO_NET_H
#define UBO_NET_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Max credential lengths (match the esp_wifi config field sizes). */
#define UBO_SSID_MAXLEN 32
#define UBO_PASS_MAXLEN 64
/* Core gRPC-Web endpoint host/port lengths. */
#define UBO_HOST_MAXLEN 64
#define UBO_PORT_MAXLEN 8

/* NVS + netif + default event loop. Needed by *any* transport (PPP-over-USB as
 * much as WiFi), so it is separable from the radio bring-up below. */
void ubo_net_init_base(void);

/* esp_wifi_init + STA netif + the station event handlers. Requires
 * ubo_net_init_base(). Skipped entirely on the USB path, which is where the
 * ~45-60KB the WiFi stack would otherwise hold comes back. */
void ubo_net_wifi_init(void);

/* ubo_net_init_base() + ubo_net_wifi_init(). Must be called once before
 * ubo_net_connect() or the captive portal (provisioning.c relies on esp_wifi
 * already being initialized). */
void ubo_net_init(void);

/* Join `ssid`/`pass` in STA mode and block until an IP is acquired or
 * `timeout_ms` elapses. Returns true on success. Requires ubo_net_init(). */
bool ubo_net_connect(const char *ssid, const char *pass, uint32_t timeout_ms);

/* Stop the STA auto-reconnect loop and disconnect, so the captive portal's
 * APSTA scan isn't disturbed by background reconnect attempts. */
void ubo_net_pause(void);

/* NVS-persisted credentials (namespace "ubo_wifi"). `ssid`/`pass` buffers must
 * hold at least UBO_SSID_MAXLEN / UBO_PASS_MAXLEN bytes. load() returns true
 * only when a non-empty SSID is stored. */
bool ubo_net_creds_load(char *ssid, char *pass);
void ubo_net_creds_save(const char *ssid, const char *pass);
void ubo_net_creds_clear(void);

/* Default ubo-core ports: Envoy's gRPC-Web listener vs the raw-TCP "tcp-lite"
 * listener (mcu_server.py). UBO_DEFAULT_PORT is whichever this build talks. */
#define UBO_DEFAULT_GRPC_WEB_PORT "50052"
#define UBO_DEFAULT_MCU_PORT "50054"
#ifdef UBO_TRANSPORT_TCP_LITE
#define UBO_DEFAULT_PORT UBO_DEFAULT_MCU_PORT
#else
#define UBO_DEFAULT_PORT UBO_DEFAULT_GRPC_WEB_PORT
#endif

/* Provisioned ubo-core endpoint (namespace "ubo_wifi"). save() stores host/port
 * (empty host -> "0.0.0.0", empty port -> UBO_DEFAULT_PORT). The two readers
 * render the same saved pair for whichever transport is built:
 *   url()  -> "http://<host>:<port>/grpc"  (gRPC-Web via Envoy)
 *   addr() -> "<host>:<port>"              (raw TCP, tcp-lite)
 * Both return false when no host was ever provisioned, so the caller falls back
 * to the Kconfig value. Cleared with the WiFi creds by ubo_net_creds_clear(). */
void ubo_net_core_save(const char *host, const char *port);
bool ubo_net_core_url(char *out, size_t out_sz);
bool ubo_net_core_addr(char *out, size_t out_sz);

/* Transport preference (namespace "ubo_wifi", key "transport"). Absent => USB,
 * i.e. "prefer the USB cable when a host is attached". Set to "wifi" from the
 * on-screen switch on the disconnect overlay, but one-shot: app_main consumes
 * it at boot and immediately resets it back to "usb", so WiFi is honored for
 * exactly the next boot and never persists across power cycles. Also cleared
 * along with the creds by ubo_net_creds_clear(). */
bool ubo_net_transport_is_wifi(void);
void ubo_net_transport_save(bool wifi);

/* The transport actually in use this boot (may differ from the stored
 * preference: pref "usb" with no host attached still boots WiFi). The on-screen
 * switch offers the *other* transport, so it saves the negation of this — never
 * a toggle of the stored preference, which would flip the wrong way in that
 * mismatched case. Set once at boot by app_main. */
void ubo_net_transport_set_active(bool wifi);
bool ubo_net_transport_active_is_wifi(void);

#ifdef __cplusplus
}
#endif
#endif /* UBO_NET_H */
