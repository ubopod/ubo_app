/* tcp-lite wire framing — transport-agnostic, MCU-portable.
 *
 * Sibling of grpc_web_frame.h for the lightweight raw-TCP transport. Every
 * tcp-lite message is a type-tagged, length-prefixed frame:
 *
 *     [1 byte message_type][varint length][protobuf payload]
 *
 * message_type is a hand-defined RPC-selector enum (mirrored byte-for-byte in
 * ubo_app/rpc/mcu_server.py — there is no shared source of truth). The length
 * is a protobuf-style base-128 varint (7 bits per byte, MSB = continuation
 * bit), little-endian group order. A server-streaming response is a
 * concatenation of such frames delivered split across arbitrary transport
 * chunk boundaries, so parsing is an incremental state machine — and because
 * the length is a varint, a frame header can split mid-varint across feeds.
 */
#ifndef UBO_TCP_LITE_FRAME_H
#define UBO_TCP_LITE_FRAME_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* RPC-selector message types. Keep byte-identical to the Python constants in
 * ubo_app/rpc/mcu_server.py. */
#define UBO_TCP_LITE_MSG_DISPATCH_ACTION_REQUEST 0x01u
#define UBO_TCP_LITE_MSG_DISPATCH_ACTION_RESPONSE 0x02u
#define UBO_TCP_LITE_MSG_SUBSCRIBE_STORE_REQUEST 0x03u
#define UBO_TCP_LITE_MSG_SUBSCRIBE_STORE_RESPONSE 0x04u
#define UBO_TCP_LITE_MSG_SUBSCRIBE_EVENT_REQUEST 0x05u
#define UBO_TCP_LITE_MSG_SUBSCRIBE_EVENT_RESPONSE 0x06u
#define UBO_TCP_LITE_MSG_ERROR 0x7Eu /* reserved */
#define UBO_TCP_LITE_MSG_PING 0x7Fu  /* reserved, future keepalive */

/* Upper bound on a single frame's wire-declared payload length. Same cap and
 * rationale as UBO_GRPC_WEB_MAX_FRAME: the largest legitimate payload is a
 * camera frame (~172KB); anything past 1 MiB is more than this client can hold.
 * Without this cap a bogus varint length would make the parser buffer grow
 * until the heap is exhausted (fatal on the 512KB-SRAM ESP32-C6). A frame past
 * the cap is discarded, not fatal — see ubo_tcp_lite_parser_take_dropped. */
#define UBO_TCP_LITE_MAX_FRAME (1u << 20)

/* Maximum number of bytes a length varint may occupy. 5 bytes carries the full
 * 32-bit range (5 * 7 = 35 bits); a length that needs a 6th continuation byte
 * is malformed and poisons the parser. */
#define UBO_TCP_LITE_MAX_VARINT_BYTES 5u

/* Frame a serialized protobuf message as [1B type][varint len][payload].
 * Returns a malloc'd buffer (caller frees) and sets *out_len; NULL on OOM. */
uint8_t *ubo_tcp_lite_encode(uint8_t message_type, const uint8_t *payload,
                             size_t payload_len, size_t *out_len);

/* Incremental frame parser. Buffers fed bytes and yields complete frames.
 * A payload pointer returned by _next() points into the internal buffer and
 * stays valid until the next _feed() call (which may compact the buffer). */
typedef struct {
    uint8_t *buf;
    size_t len;   /* bytes currently buffered */
    size_t pos;   /* read offset of the next unparsed frame */
    size_t cap;   /* allocated capacity */
    size_t skip;  /* payload bytes of an oversized frame still to be discarded */
    bool dropped; /* an oversized frame was discarded since the last _take_ */
    bool bad;     /* poisoned: malformed varint, so framing is unrecoverable */
} ubo_tcp_lite_parser;

void ubo_tcp_lite_parser_init(ubo_tcp_lite_parser *p);
void ubo_tcp_lite_parser_free(ubo_tcp_lite_parser *p);

/* Append `len` bytes. Returns false on OOM or when the parser is poisoned
 * (see ubo_tcp_lite_parser_bad); the caller should abort the stream. */
bool ubo_tcp_lite_parser_feed(ubo_tcp_lite_parser *p, const uint8_t *data,
                              size_t len);

/* True once a length varint failed to terminate within
 * UBO_TCP_LITE_MAX_VARINT_BYTES (or overflowed size_t). The declared length is
 * then unknown, so the parser cannot tell where the next header starts: it
 * yields nothing further and the stream should be dropped (the reconnect loop
 * starts a fresh one). An oversized-but-well-formed length does NOT poison the
 * parser: it is skipped instead. */
bool ubo_tcp_lite_parser_bad(const ubo_tcp_lite_parser *p);

/* Consume the "an oversized frame was discarded" flag, for a caller that wants
 * to log it. One message is lost; the stream stays usable. */
bool ubo_tcp_lite_parser_take_dropped(ubo_tcp_lite_parser *p);

/* Pop the next complete frame. Returns true and sets *message_type / *payload /
 * *payload_len when a frame is available; false when more bytes are needed. */
bool ubo_tcp_lite_parser_next(ubo_tcp_lite_parser *p, uint8_t *message_type,
                              const uint8_t **payload, size_t *payload_len);

#endif /* UBO_TCP_LITE_FRAME_H */
