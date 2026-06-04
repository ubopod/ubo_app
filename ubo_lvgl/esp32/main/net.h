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

/* One-time bring-up: NVS + netif + default event loop + esp_wifi_init + STA
 * netif + the station event handlers. Must be called once before
 * ubo_net_connect() or the captive portal. */
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

/* Provisioned ubo-core endpoint (namespace "ubo_wifi"). save() stores host/port
 * (empty host -> "0.0.0.0", empty port -> "50052"). url() formats the saved
 * values into `out` as "http://<host>:<port>/grpc" and returns true; it returns
 * false when no host was ever provisioned (caller falls back to the Kconfig
 * URL). Cleared together with the WiFi creds by ubo_net_creds_clear(). */
void ubo_net_core_save(const char *host, const char *port);
bool ubo_net_core_url(char *out, size_t out_sz);

#ifdef __cplusplus
}
#endif
#endif /* UBO_NET_H */
