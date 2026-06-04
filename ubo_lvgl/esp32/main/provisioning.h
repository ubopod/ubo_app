/**
 * @file provisioning.h
 * WiFi captive-portal provisioning for the ESP32-C6.
 *
 * When STA connect fails, bring up a SoftAP ("ubo-setup") with a DNS catch-all
 * and an HTTP form so a user can pick their network from a scan, enter the
 * password, and have the device persist the creds to NVS and reboot onto it.
 */
#ifndef UBO_PROVISIONING_H
#define UBO_PROVISIONING_H

#ifdef __cplusplus
extern "C" {
#endif

/* Start the SoftAP + DNS + HTTP captive portal and block. On a successful form
 * submit the creds are saved to NVS and the device reboots (does not return).
 * Requires ubo_net_init() to have run (esp_wifi already initialized). */
void ubo_provisioning_run(void);

#ifdef __cplusplus
}
#endif
#endif /* UBO_PROVISIONING_H */
