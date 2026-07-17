/**
 * @file usb_ppp.h
 * PPP/IP over the ESP32-C6's USB Serial/JTAG port, so the USB cable that flashes
 * the board can also carry gRPC-Web traffic to ubo-core.
 *
 * The C6 has no USB-OTG — its only USB is the fixed-function Serial/JTAG CDC-ACM
 * controller — so USB-Ethernet (NCM/ECM) is impossible and the wire carries a
 * standard PPP link instead: an lwIP PPP client here, `pppd` on the Pi. Addresses
 * come from pppd's IPCP (10.66.0.1 Pi / 10.66.0.2 ESP32); nothing is configured
 * statically on this side.
 *
 * Requires the `.ppp` build profile:
 *   idf.py -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.ppp" build
 * which enables CONFIG_LWIP_PPP_SUPPORT and, crucially, sets
 * CONFIG_ESP_CONSOLE_SECONDARY_NONE — PPP must own the USJ endpoint, so logs no
 * longer mirror to USB (the primary UART0 console still gets them).
 */
#ifndef UBO_USB_PPP_H
#define UBO_USB_PPP_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* True when a USB host is attached, i.e. the port is receiving SOF packets. A
 * bare charger/power bank never sends SOF, so it reads as "no host" — this is
 * what makes the boot-time USB probe free when the board is only being powered.
 *
 * It is a *gate*, not proof that pppd is listening; ubo_usb_ppp_start() is
 * authoritative. Safe to call before ubo_usb_ppp_start() (the SOF monitor is a
 * FreeRTOS tick hook registered at system init, independent of the USJ driver),
 * but it costs a little time on every tick, so call it once at boot rather than
 * polling it. */
bool ubo_usb_ppp_host_present(void);

/* Bring the PPP link up: install the USJ driver + PPP netif on first call, kick
 * LCP, and block until IPCP hands us an address or `timeout_ms` elapses.
 * Returns 0 on success, -1 on timeout/failure (call ubo_usb_ppp_stop() then). */
int ubo_usb_ppp_start(uint32_t timeout_ms);

/* Tear the link down (keeps the driver + netif for a subsequent start()). */
void ubo_usb_ppp_stop(void);

/* Block until the link goes down. Returns immediately if it is already down. */
void ubo_usb_ppp_wait_link_down(void);

#ifdef __cplusplus
}
#endif
#endif /* UBO_USB_PPP_H */
