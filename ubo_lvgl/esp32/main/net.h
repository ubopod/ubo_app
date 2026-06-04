/**
 * @file net.h
 * Minimal WiFi station bring-up for the ESP32-C6 (2.4GHz).
 */
#ifndef UBO_NET_H
#define UBO_NET_H

#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Initialize NVS + WiFi, join `ssid`/`pass`, and block until an IP is acquired
 * (or the retry budget is exhausted). Returns true on success. */
bool ubo_net_connect(const char *ssid, const char *pass);

#ifdef __cplusplus
}
#endif
#endif /* UBO_NET_H */
