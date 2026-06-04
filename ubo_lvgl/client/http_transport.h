/* Thin HTTP/1.1 transport for gRPC-Web — libcurl backend (macOS/Linux).
 *
 * The interface is intentionally minimal and platform-neutral so an ESP-IDF
 * backend (esp_http_client) can implement the same two calls: one unary POST
 * (collect the full response body) and one streaming POST (invoke a callback
 * per response-body chunk until the stream ends or a stop flag is set).
 *
 * The gRPC-Web headers (application/grpc-web+proto, x-grpc-web) are applied
 * internally. Callers pass the request path; the full URL is base_url + path.
 */
#ifndef UBO_HTTP_TRANSPORT_H
#define UBO_HTTP_TRANSPORT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct ubo_http ubo_http;

/* Create a transport bound to an Envoy "/grpc" base URL
 * (e.g. "http://localhost:50052/grpc"). Returns NULL on failure. */
ubo_http *ubo_http_create(const char *base_url);
void ubo_http_destroy(ubo_http *h);

/* Unary POST: send `body`, collect the entire response body into *out
 * (malloc'd, caller frees) and *out_len. *http_status receives the HTTP status.
 * Any of out/out_len/http_status may be NULL. Returns 0 on success, <0 on a
 * transport error. */
int ubo_http_post_unary(ubo_http *h, const char *path, const uint8_t *body,
                        size_t body_len, uint8_t **out, size_t *out_len,
                        long *http_status);

/* Streaming POST: send `body`, then invoke on_chunk(user, data, len) for each
 * response-body chunk as it arrives. Blocks until the server closes the stream,
 * an error occurs, or *stop becomes true (stop may be NULL). Returns 0 on a
 * clean end, <0 on a transport error. */
typedef void (*ubo_http_chunk_cb)(void *user, const uint8_t *data, size_t len);

int ubo_http_post_stream(ubo_http *h, const char *path, const uint8_t *body,
                         size_t body_len, ubo_http_chunk_cb on_chunk, void *user,
                         volatile bool *stop);

#endif /* UBO_HTTP_TRANSPORT_H */
