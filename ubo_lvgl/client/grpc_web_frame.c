#include "grpc_web_frame.h"

#include <stdlib.h>
#include <string.h>

uint8_t *ubo_grpc_web_encode(const uint8_t *payload, size_t payload_len,
                             size_t *out_len) {
    size_t total = UBO_GRPC_WEB_HEADER_SIZE + payload_len;
    uint8_t *out = malloc(total);
    if (!out) {
        return NULL;
    }
    out[0] = UBO_GRPC_WEB_DATA_FLAG;
    out[1] = (uint8_t)((payload_len >> 24) & 0xFF);
    out[2] = (uint8_t)((payload_len >> 16) & 0xFF);
    out[3] = (uint8_t)((payload_len >> 8) & 0xFF);
    out[4] = (uint8_t)(payload_len & 0xFF);
    if (payload_len) {
        memcpy(out + UBO_GRPC_WEB_HEADER_SIZE, payload, payload_len);
    }
    *out_len = total;
    return out;
}

bool ubo_grpc_web_is_trailer(uint8_t flag) {
    return (flag & UBO_GRPC_WEB_TRAILER_FLAG) != 0;
}

long ubo_grpc_web_parse_trailer(const uint8_t *payload, size_t len, char *msg,
                                size_t msg_cap) {
    if (msg && msg_cap) {
        msg[0] = '\0';
    }
    long status = 0;
    size_t i = 0;
    while (i < len) {
        /* Find end of line. */
        size_t start = i;
        while (i < len && payload[i] != '\n') {
            i++;
        }
        size_t end = i; /* exclusive; may include a trailing '\r' */
        if (i < len) {
            i++; /* skip '\n' */
        }
        if (end > start && payload[end - 1] == '\r') {
            end--;
        }
        if (end == start) {
            continue; /* blank line */
        }
        /* Split on the first ':'. */
        size_t colon = start;
        while (colon < end && payload[colon] != ':') {
            colon++;
        }
        if (colon >= end) {
            continue;
        }
        const char *key = (const char *)payload + start;
        size_t key_len = colon - start;
        const char *val = (const char *)payload + colon + 1;
        size_t val_len = end - (colon + 1);
        /* Trim leading spaces from value. */
        while (val_len && *val == ' ') {
            val++;
            val_len--;
        }
        if (key_len == 11 && strncmp(key, "grpc-status", 11) == 0) {
            char tmp[24];
            size_t n = val_len < sizeof(tmp) - 1 ? val_len : sizeof(tmp) - 1;
            memcpy(tmp, val, n);
            tmp[n] = '\0';
            status = strtol(tmp, NULL, 10);
        } else if (key_len == 12 && strncmp(key, "grpc-message", 12) == 0 && msg &&
                   msg_cap) {
            size_t n = val_len < msg_cap - 1 ? val_len : msg_cap - 1;
            memcpy(msg, val, n);
            msg[n] = '\0';
        }
    }
    return status;
}

void ubo_grpc_web_parser_init(ubo_grpc_web_parser *p) {
    p->buf = NULL;
    p->len = 0;
    p->pos = 0;
    p->cap = 0;
    p->skip = 0;
    p->dropped = false;
    p->bad = false;
}

void ubo_grpc_web_parser_free(ubo_grpc_web_parser *p) {
    free(p->buf);
    p->buf = NULL;
    p->len = p->pos = p->cap = p->skip = 0;
    p->dropped = false;
    p->bad = false;
}

bool ubo_grpc_web_parser_bad(const ubo_grpc_web_parser *p) {
    return p->bad;
}

bool ubo_grpc_web_parser_take_dropped(ubo_grpc_web_parser *p) {
    bool dropped = p->dropped;
    p->dropped = false;
    return dropped;
}

bool ubo_grpc_web_parser_feed(ubo_grpc_web_parser *p, const uint8_t *data,
                              size_t len) {
    if (p->bad) {
        return false;
    }
    /* Swallow the tail of an oversized frame before it can reach the buffer.
     * When skipping, everything buffered has already been consumed. */
    if (p->skip) {
        size_t n = p->skip < len ? p->skip : len;
        p->skip -= n;
        data += n;
        len -= n;
    }
    /* Reclaim already-consumed bytes from the front first. */
    if (p->pos > 0) {
        memmove(p->buf, p->buf + p->pos, p->len - p->pos);
        p->len -= p->pos;
        p->pos = 0;
    }
    /* Backstop: with callers draining after every feed, buffered bytes never
     * legitimately exceed one max frame plus one transport chunk. */
    if (p->len + len > (size_t)UBO_GRPC_WEB_MAX_FRAME * 2) {
        p->bad = true;
        return false;
    }
    if (p->len + len > p->cap) {
        size_t cap = p->cap ? p->cap : 256;
        while (cap < p->len + len) {
            cap *= 2;
        }
        uint8_t *nbuf = realloc(p->buf, cap);
        if (!nbuf) {
            return false;
        }
        p->buf = nbuf;
        p->cap = cap;
    }
    if (len) {
        memcpy(p->buf + p->len, data, len);
        p->len += len;
    }
    return true;
}

bool ubo_grpc_web_parser_next(ubo_grpc_web_parser *p, uint8_t *flag,
                              const uint8_t **payload, size_t *payload_len) {
    while (!p->bad && p->skip == 0) {
        size_t avail = p->len - p->pos;
        if (avail < UBO_GRPC_WEB_HEADER_SIZE) {
            return false;
        }
        const uint8_t *h = p->buf + p->pos;
        uint32_t plen = ((uint32_t)h[1] << 24) | ((uint32_t)h[2] << 16) |
                        ((uint32_t)h[3] << 8) | (uint32_t)h[4];
        if (plen > UBO_GRPC_WEB_MAX_FRAME) {
            /* Too big for this client to hold, but the frame is self-
             * delimiting: discard exactly its payload and resynchronise on the
             * next header. Tearing the stream down instead would kill BOTH the
             * store and event streams and knock the device off the air over one
             * unrenderable message. */
            size_t body = avail - UBO_GRPC_WEB_HEADER_SIZE;
            size_t drop = body < plen ? body : plen;
            p->pos += UBO_GRPC_WEB_HEADER_SIZE + drop;
            p->skip = plen - drop;
            p->dropped = true;
            continue;
        }
        if (avail < UBO_GRPC_WEB_HEADER_SIZE + plen) {
            return false;
        }
        *flag = h[0];
        *payload = h + UBO_GRPC_WEB_HEADER_SIZE;
        *payload_len = plen;
        p->pos += UBO_GRPC_WEB_HEADER_SIZE + plen;
        return true;
    }
    return false;
}
