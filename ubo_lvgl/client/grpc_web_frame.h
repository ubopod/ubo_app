/* gRPC-Web wire framing — transport-agnostic, MCU-portable.
 *
 * C port of the Python ubo_lvgl_gui_client/grpc_web_frame.py. Every gRPC-Web
 * message is a length-prefixed frame:
 *
 *     [1 byte flag][4 bytes big-endian length][payload]
 *
 * flag bit 0x80 marks a trailer frame (carrying grpc-status / grpc-message);
 * flag 0x00 marks a data frame (a serialized protobuf message). A server-
 * streaming response is a concatenation of such frames delivered split across
 * arbitrary HTTP chunk boundaries, so parsing is an incremental state machine.
 */
#ifndef UBO_GRPC_WEB_FRAME_H
#define UBO_GRPC_WEB_FRAME_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define UBO_GRPC_WEB_DATA_FLAG 0x00u
#define UBO_GRPC_WEB_TRAILER_FLAG 0x80u
#define UBO_GRPC_WEB_HEADER_SIZE 5u

/* Wrap a serialized protobuf message in a single gRPC-Web data frame.
 * Returns a malloc'd buffer (caller frees) and sets *out_len; NULL on OOM. */
uint8_t *ubo_grpc_web_encode(const uint8_t *payload, size_t payload_len,
                             size_t *out_len);

/* True if a frame flag marks a trailer (vs a data) frame. */
bool ubo_grpc_web_is_trailer(uint8_t flag);

/* Parse a trailer payload (lines of "key:value\r\n"). Returns the numeric
 * grpc-status (0 if absent), and copies grpc-message into msg[msg_cap]
 * (empty string if absent / msg NULL). */
long ubo_grpc_web_parse_trailer(const uint8_t *payload, size_t len, char *msg,
                                size_t msg_cap);

/* Incremental frame parser. Buffers fed bytes and yields complete frames.
 * A payload pointer returned by _next() points into the internal buffer and
 * stays valid until the next _feed() call (which may compact the buffer). */
typedef struct {
    uint8_t *buf;
    size_t len; /* bytes currently buffered */
    size_t pos; /* read offset of the next unparsed frame */
    size_t cap; /* allocated capacity */
} ubo_grpc_web_parser;

void ubo_grpc_web_parser_init(ubo_grpc_web_parser *p);
void ubo_grpc_web_parser_free(ubo_grpc_web_parser *p);

/* Append `len` bytes. Returns false on OOM. */
bool ubo_grpc_web_parser_feed(ubo_grpc_web_parser *p, const uint8_t *data,
                              size_t len);

/* Pop the next complete frame. Returns true and sets *flag / *payload /
 * *payload_len when a frame is available; false when more bytes are needed. */
bool ubo_grpc_web_parser_next(ubo_grpc_web_parser *p, uint8_t *flag,
                              const uint8_t **payload, size_t *payload_len);

#endif /* UBO_GRPC_WEB_FRAME_H */
