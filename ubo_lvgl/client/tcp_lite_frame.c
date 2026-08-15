#include "tcp_lite_frame.h"

#include <stdlib.h>
#include <string.h>

/* Encode `value` as a base-128 varint into out[]; returns the byte count.
 * out must hold at least UBO_TCP_LITE_MAX_VARINT_BYTES bytes. */
static size_t encode_varint(size_t value, uint8_t *out) {
    size_t i = 0;
    for (;;) {
        uint8_t byte = (uint8_t)(value & 0x7Fu);
        value >>= 7;
        if (value) {
            out[i++] = byte | 0x80u;
        } else {
            out[i++] = byte;
            return i;
        }
    }
}

uint8_t *ubo_tcp_lite_encode(uint8_t message_type, const uint8_t *payload,
                             size_t payload_len, size_t *out_len) {
    uint8_t vbuf[UBO_TCP_LITE_MAX_VARINT_BYTES];
    size_t vlen = encode_varint(payload_len, vbuf);
    size_t total = 1 + vlen + payload_len;
    uint8_t *out = malloc(total);
    if (!out) {
        return NULL;
    }
    out[0] = message_type;
    memcpy(out + 1, vbuf, vlen);
    if (payload_len) {
        memcpy(out + 1 + vlen, payload, payload_len);
    }
    *out_len = total;
    return out;
}

void ubo_tcp_lite_parser_init(ubo_tcp_lite_parser *p) {
    p->buf = NULL;
    p->len = 0;
    p->pos = 0;
    p->cap = 0;
    p->skip = 0;
    p->dropped = false;
    p->bad = false;
}

void ubo_tcp_lite_parser_free(ubo_tcp_lite_parser *p) {
    free(p->buf);
    p->buf = NULL;
    p->len = p->pos = p->cap = p->skip = 0;
    p->dropped = false;
    p->bad = false;
}

bool ubo_tcp_lite_parser_bad(const ubo_tcp_lite_parser *p) {
    return p->bad;
}

bool ubo_tcp_lite_parser_take_dropped(ubo_tcp_lite_parser *p) {
    bool dropped = p->dropped;
    p->dropped = false;
    return dropped;
}

bool ubo_tcp_lite_parser_feed(ubo_tcp_lite_parser *p, const uint8_t *data,
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
    if (p->len + len > (size_t)UBO_TCP_LITE_MAX_FRAME * 2) {
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

bool ubo_tcp_lite_parser_next(ubo_tcp_lite_parser *p, uint8_t *message_type,
                              const uint8_t **payload, size_t *payload_len) {
    while (!p->bad && p->skip == 0) {
        size_t avail = p->len - p->pos;
        if (avail < 1) {
            return false; /* need at least the message-type byte */
        }
        const uint8_t *h = p->buf + p->pos;
        /* Decode the length varint, which may still be arriving byte-by-byte. */
        size_t plen = 0;
        unsigned shift = 0;
        size_t vbytes = 0;
        bool complete = false;
        while (vbytes < UBO_TCP_LITE_MAX_VARINT_BYTES) {
            if (1 + vbytes >= avail) {
                return false; /* varint not fully buffered yet — wait for more */
            }
            uint8_t byte = h[1 + vbytes];
            size_t chunk = (size_t)(byte & 0x7Fu);
            if ((chunk << shift) >> shift != chunk) {
                /* Shifting would drop bits (size_t too narrow for this varint,
                 * e.g. a 32-bit target) — poison rather than silently truncate
                 * the declared length. */
                p->bad = true;
                return false;
            }
            plen |= chunk << shift;
            vbytes++;
            if (!(byte & 0x80u)) {
                complete = true;
                break;
            }
            shift += 7;
        }
        if (!complete) {
            /* Continuation bit still set past the byte cap: a malformed,
             * non-terminating length header. The frame length is unknowable, so
             * there is no way to find the next header — poison. */
            p->bad = true;
            return false;
        }
        size_t header_len = 1 + vbytes;
        if (plen > UBO_TCP_LITE_MAX_FRAME) {
            /* Too big for this client to hold, but the frame is self-
             * delimiting: discard exactly its payload and resynchronise on the
             * next header rather than tearing the stream down. See the matching
             * comment in grpc_web_frame.c. */
            size_t body = avail - header_len;
            size_t drop = body < plen ? body : plen;
            p->pos += header_len + drop;
            p->skip = plen - drop;
            p->dropped = true;
            continue;
        }
        if (avail < header_len + plen) {
            return false; /* payload not fully buffered yet */
        }
        *message_type = h[0];
        *payload = h + header_len;
        *payload_len = plen;
        p->pos += header_len + plen;
        return true;
    }
    return false;
}
