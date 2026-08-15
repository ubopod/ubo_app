/* Persistent-socket transport for the tcp-lite RPC path.
 *
 * Sibling of http_transport.h, but shaped for a raw TCP link rather than
 * request/response-per-call HTTP: there is no HTTP call boundary here, so a
 * connection is opened, written to, then streamed from until the caller stops
 * it. One file serves both desktop and ESP32 — raw BSD sockets work on both
 * (ESP32-C6's lwIP exposes lwip/sockets.h, per esp32/components/dns_server).
 *
 * Return codes follow http_transport.h: 0 on success, <0 on error.
 */
#ifndef UBO_TCP_LITE_TRANSPORT_H
#define UBO_TCP_LITE_TRANSPORT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct ubo_tcp_lite ubo_tcp_lite;

/* Resolve (getaddrinfo) and connect to "host:port", split on the LAST ':'.
 * Only a plain hostname / IPv4 literal is supported (matching the existing
 * --host flag's scope; no IPv6-bracket handling). Returns NULL on a
 * DNS/connect failure. */
ubo_tcp_lite *ubo_tcp_lite_connect(const char *host_port);
void ubo_tcp_lite_close(ubo_tcp_lite *t);

/* Write `len` bytes, retrying short writes. Returns 0 on success, <0 on a
 * socket error. */
int ubo_tcp_lite_write(ubo_tcp_lite *t, const uint8_t *data, size_t len);

/* Invoked per received transport chunk. Return false to stop the read loop
 * (the caller has what it needs, or the payload is unrecoverable). */
typedef bool (*ubo_tcp_lite_chunk_cb)(void *user, const uint8_t *data,
                                      size_t len);

/* Block reading from the socket, feeding raw bytes to on_chunk, until either
 * on_chunk returns false, *stop becomes true (stop may be NULL), or the
 * connection errors/EOFs. A ~1s SO_RCVTIMEO ensures *stop is polled even when
 * the peer is silent — mirrors ubo_http_post_stream's stop-flag contract.
 * Returns 0 on a clean end (peer closed / stop set), <0 on a socket error or
 * callback abort. */
int ubo_tcp_lite_read_loop(ubo_tcp_lite *t, ubo_tcp_lite_chunk_cb on_chunk,
                           void *user, volatile bool *stop);

#endif /* UBO_TCP_LITE_TRANSPORT_H */
