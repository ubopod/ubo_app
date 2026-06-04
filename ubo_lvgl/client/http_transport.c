#include "http_transport.h"

#include <pthread.h>
#include <stdlib.h>
#include <string.h>

#include <curl/curl.h>

struct ubo_http {
    char *base_url;
    struct curl_slist *headers;
};

static pthread_once_t g_curl_once = PTHREAD_ONCE_INIT;
static void curl_global_once(void) { curl_global_init(CURL_GLOBAL_DEFAULT); }

ubo_http *ubo_http_create(const char *base_url) {
    pthread_once(&g_curl_once, curl_global_once);
    ubo_http *h = calloc(1, sizeof(*h));
    if (!h) {
        return NULL;
    }
    h->base_url = strdup(base_url);
    if (!h->base_url) {
        free(h);
        return NULL;
    }
    h->headers = curl_slist_append(NULL, "content-type: application/grpc-web+proto");
    h->headers = curl_slist_append(h->headers, "accept: application/grpc-web+proto");
    h->headers = curl_slist_append(h->headers, "x-grpc-web: 1");
    h->headers = curl_slist_append(h->headers,
                                   "x-user-agent: ubo-lvgl-client/grpc-web");
    return h;
}

void ubo_http_destroy(ubo_http *h) {
    if (!h) {
        return;
    }
    curl_slist_free_all(h->headers);
    free(h->base_url);
    free(h);
}

static CURL *make_handle(ubo_http *h, const char *path, const uint8_t *body,
                         size_t body_len, char *url, size_t url_cap) {
    snprintf(url, url_cap, "%s%s", h->base_url, path);
    CURL *c = curl_easy_init();
    if (!c) {
        return NULL;
    }
    curl_easy_setopt(c, CURLOPT_URL, url);
    curl_easy_setopt(c, CURLOPT_POST, 1L);
    curl_easy_setopt(c, CURLOPT_POSTFIELDS, body);
    curl_easy_setopt(c, CURLOPT_POSTFIELDSIZE, (long)body_len);
    curl_easy_setopt(c, CURLOPT_HTTPHEADER, h->headers);
    curl_easy_setopt(c, CURLOPT_CONNECTTIMEOUT, 5L);
    /* HTTP/1.1: Envoy serves gRPC-Web over 1.1; keep it explicit. */
    curl_easy_setopt(c, CURLOPT_HTTP_VERSION, CURL_HTTP_VERSION_1_1);
    if (getenv("UBO_RPC_DEBUG")) {
        curl_easy_setopt(c, CURLOPT_VERBOSE, 1L);
    }
    return c;
}

/* ── Unary ── */
struct buf {
    uint8_t *data;
    size_t len;
    size_t cap;
};

static size_t collect_cb(char *ptr, size_t size, size_t nmemb, void *userp) {
    size_t n = size * nmemb;
    struct buf *b = userp;
    if (b->len + n > b->cap) {
        size_t cap = b->cap ? b->cap : 256;
        while (cap < b->len + n) {
            cap *= 2;
        }
        uint8_t *nd = realloc(b->data, cap);
        if (!nd) {
            return 0; /* abort */
        }
        b->data = nd;
        b->cap = cap;
    }
    memcpy(b->data + b->len, ptr, n);
    b->len += n;
    return n;
}

int ubo_http_post_unary(ubo_http *h, const char *path, const uint8_t *body,
                        size_t body_len, uint8_t **out, size_t *out_len,
                        long *http_status) {
    char url[512];
    CURL *c = make_handle(h, path, body, body_len, url, sizeof(url));
    if (!c) {
        return -1;
    }
    struct buf b = {0};
    curl_easy_setopt(c, CURLOPT_WRITEFUNCTION, collect_cb);
    curl_easy_setopt(c, CURLOPT_WRITEDATA, &b);
    CURLcode rc = curl_easy_perform(c);
    long status = 0;
    curl_easy_getinfo(c, CURLINFO_RESPONSE_CODE, &status);
    curl_easy_cleanup(c);
    if (http_status) {
        *http_status = status;
    }
    if (rc != CURLE_OK) {
        free(b.data);
        return -1;
    }
    if (out) {
        *out = b.data;
    } else {
        free(b.data);
    }
    if (out_len) {
        *out_len = b.len;
    }
    return 0;
}

/* ── Streaming ── */
struct stream_ctx {
    ubo_http_chunk_cb on_chunk;
    void *user;
    volatile bool *stop;
};

static size_t stream_write_cb(char *ptr, size_t size, size_t nmemb, void *userp) {
    size_t n = size * nmemb;
    struct stream_ctx *s = userp;
    if (s->stop && *s->stop) {
        return 0; /* abort transfer */
    }
    if (n && s->on_chunk) {
        s->on_chunk(s->user, (const uint8_t *)ptr, n);
    }
    return n;
}

static int stream_progress_cb(void *userp, curl_off_t dltotal, curl_off_t dlnow,
                              curl_off_t ultotal, curl_off_t ulnow) {
    (void)dltotal;
    (void)dlnow;
    (void)ultotal;
    (void)ulnow;
    struct stream_ctx *s = userp;
    return (s->stop && *s->stop) ? 1 : 0; /* non-zero aborts */
}

int ubo_http_post_stream(ubo_http *h, const char *path, const uint8_t *body,
                         size_t body_len, ubo_http_chunk_cb on_chunk, void *user,
                         volatile bool *stop) {
    char url[512];
    CURL *c = make_handle(h, path, body, body_len, url, sizeof(url));
    if (!c) {
        return -1;
    }
    struct stream_ctx s = {on_chunk, user, stop};
    curl_easy_setopt(c, CURLOPT_WRITEFUNCTION, stream_write_cb);
    curl_easy_setopt(c, CURLOPT_WRITEDATA, &s);
    curl_easy_setopt(c, CURLOPT_NOPROGRESS, 0L);
    curl_easy_setopt(c, CURLOPT_XFERINFOFUNCTION, stream_progress_cb);
    curl_easy_setopt(c, CURLOPT_XFERINFODATA, &s);
    CURLcode rc = curl_easy_perform(c);
    long status = 0;
    curl_easy_getinfo(c, CURLINFO_RESPONSE_CODE, &status);
    curl_easy_cleanup(c);
    /* A stop-triggered abort surfaces as ABORTED_BY_CALLBACK / WRITE_ERROR;
     * treat that as a clean end, not a transport error. */
    if (stop && *stop) {
        return 0;
    }
    /* A non-200 (e.g. Envoy 503 when core is down) is reported as an error so
     * the caller's reconnect loop kicks in, even though curl itself succeeded. */
    if (rc != CURLE_OK || status != 200) {
        return -1;
    }
    return 0;
}
