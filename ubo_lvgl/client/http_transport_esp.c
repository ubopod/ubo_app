/* ESP-IDF backend for the gRPC-Web HTTP transport (http_transport.h).
 *
 * Mirrors the libcurl backend (http_transport.c) over esp_http_client:
 *   - one unary POST that collects the whole response body, and
 *   - one streaming POST that feeds each response chunk to a callback until the
 *     server closes the stream or *stop is set.
 *
 * Only compiled on ESP_PLATFORM; the desktop build uses http_transport.c.
 */
#ifdef ESP_PLATFORM

#include "http_transport.h"

#include <stdlib.h>
#include <string.h>

#include "esp_http_client.h"
#include "esp_log.h"

static const char *TAG = "ubo_http";

/* Per-read socket timeout. A streaming subscribe is mostly idle (a static
 * screen sends nothing), so a read that times out with no data returns
 * -ESP_ERR_HTTP_EAGAIN and is treated as "still connected, keep waiting" — NOT
 * a disconnect. Kept short so the loop re-checks *stop responsively. */
#define HTTP_TIMEOUT_MS 5000
/* Once a stream is connected, drop the per-read timeout low: esp_http_client_read
 * holds buffered data until its buffer fills OR this timeout expires, so this is
 * effectively the view-update latency (a fast poll over the pushed stream). */
#define HTTP_STREAM_READ_TIMEOUT_MS 100
#define HTTP_READ_CHUNK 1024

struct ubo_http {
    char *base_url;
};

ubo_http *ubo_http_create(const char *base_url) {
    ubo_http *h = calloc(1, sizeof(*h));
    if (!h) {
        return NULL;
    }
    h->base_url = strdup(base_url);
    if (!h->base_url) {
        free(h);
        return NULL;
    }
    return h;
}

void ubo_http_destroy(ubo_http *h) {
    if (!h) {
        return;
    }
    free(h->base_url);
    free(h);
}

/* Build a client, set the gRPC-Web headers, open the connection and write the
 * request body. Returns the open client (caller closes/cleans up) or NULL. */
static esp_http_client_handle_t open_post(ubo_http *h, const char *path,
                                          const uint8_t *body, size_t body_len) {
    size_t url_len = strlen(h->base_url) + strlen(path) + 1;
    char *url = malloc(url_len);
    if (!url) {
        return NULL;
    }
    snprintf(url, url_len, "%s%s", h->base_url, path);

    const esp_http_client_config_t cfg = {
        .url = url,
        .method = HTTP_METHOD_POST,
        .timeout_ms = HTTP_TIMEOUT_MS,
        .buffer_size = HTTP_READ_CHUNK,
        .buffer_size_tx = HTTP_READ_CHUNK,
    };
    esp_http_client_handle_t c = esp_http_client_init(&cfg);
    free(url);
    if (!c) {
        return NULL;
    }
    esp_http_client_set_header(c, "Content-Type", "application/grpc-web+proto");
    esp_http_client_set_header(c, "Accept", "application/grpc-web+proto");
    esp_http_client_set_header(c, "x-grpc-web", "1");
    esp_http_client_set_header(c, "x-user-agent", "ubo-lvgl-client/grpc-web");

    esp_err_t err = esp_http_client_open(c, (int)body_len);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "open %s failed: %s", path, esp_err_to_name(err));
        esp_http_client_cleanup(c);
        return NULL;
    }
    if (body_len > 0) {
        int w = esp_http_client_write(c, (const char *)body, (int)body_len);
        if (w < 0 || (size_t)w != body_len) {
            ESP_LOGW(TAG, "write %s short (%d/%zu)", path, w, body_len);
            esp_http_client_close(c);
            esp_http_client_cleanup(c);
            return NULL;
        }
    }
    if (esp_http_client_fetch_headers(c) < 0) {
        ESP_LOGW(TAG, "fetch_headers %s failed", path);
        esp_http_client_close(c);
        esp_http_client_cleanup(c);
        return NULL;
    }
    return c;
}

int ubo_http_post_unary(ubo_http *h, const char *path, const uint8_t *body,
                        size_t body_len, uint8_t **out, size_t *out_len,
                        long *http_status) {
    esp_http_client_handle_t c = open_post(h, path, body, body_len);
    if (!c) {
        return -1;
    }
    if (http_status) {
        *http_status = esp_http_client_get_status_code(c);
    }

    uint8_t *buf = NULL;
    size_t len = 0, cap = 0;
    uint8_t chunk[HTTP_READ_CHUNK];
    int rc = 0;
    for (;;) {
        int n = esp_http_client_read(c, (char *)chunk, sizeof(chunk));
        if (n == -ESP_ERR_HTTP_EAGAIN) {
            continue; /* slow server, no data yet — keep reading */
        }
        if (n < 0) {
            rc = -1;
            break;
        }
        if (n == 0) {
            if (esp_http_client_is_complete_data_received(c)) {
                break;
            }
            continue;
        }
        if (len + (size_t)n > cap) {
            size_t ncap = cap ? cap * 2 : 256;
            while (ncap < len + (size_t)n) {
                ncap *= 2;
            }
            uint8_t *nb = realloc(buf, ncap);
            if (!nb) {
                rc = -1;
                break;
            }
            buf = nb;
            cap = ncap;
        }
        memcpy(buf + len, chunk, (size_t)n);
        len += (size_t)n;
    }
    esp_http_client_close(c);
    esp_http_client_cleanup(c);

    if (rc != 0) {
        free(buf);
        return -1;
    }
    if (out) {
        *out = buf;
    } else {
        free(buf);
    }
    if (out_len) {
        *out_len = len;
    }
    return 0;
}

int ubo_http_post_stream(ubo_http *h, const char *path, const uint8_t *body,
                         size_t body_len, ubo_http_chunk_cb on_chunk, void *user,
                         volatile bool *stop) {
    esp_http_client_handle_t c = open_post(h, path, body, body_len);
    if (!c) {
        return -1;
    }
    const long status = esp_http_client_get_status_code(c);

    /* Connected: shorten the read timeout so pushed view updates flush promptly
     * instead of being held until the (long) connect timeout. */
    esp_http_client_set_timeout_ms(c, HTTP_STREAM_READ_TIMEOUT_MS);

    int rc = 0;
    uint8_t chunk[HTTP_READ_CHUNK];
    while (!(stop && *stop)) {
        int n = esp_http_client_read(c, (char *)chunk, sizeof(chunk));
        if (n > 0) {
            if (on_chunk) {
                on_chunk(user, chunk, (size_t)n);
            }
        } else if (n == 0) {
            if (esp_http_client_is_complete_data_received(c)) {
                break; /* server closed the stream cleanly */
            }
            /* idle with no data: re-check stop and keep going */
        } else if (n == -ESP_ERR_HTTP_EAGAIN) {
            /* read timed out before any data — the stream is just idle, not
             * dead. Keep waiting (the while-condition re-checks *stop). */
            continue;
        } else {
            rc = -1; /* real transport error */
            break;
        }
    }
    esp_http_client_close(c);
    esp_http_client_cleanup(c);

    if (stop && *stop) {
        return 0;
    }
    /* A non-200 (e.g. Envoy 503 when core is down) is reported as an error so
     * the caller's reconnect loop engages. */
    if (rc != 0 || status != 200) {
        return -1;
    }
    return 0;
}

#endif /* ESP_PLATFORM */
