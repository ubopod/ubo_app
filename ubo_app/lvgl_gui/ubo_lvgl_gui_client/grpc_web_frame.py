"""gRPC-Web wire framing — transport-agnostic and MCU-portable.

This module is deliberately dependency-free. It models the exact byte layout an
ESP32 port will reproduce in C. Every gRPC-Web message is a length-prefixed
frame::

    [1 byte flag][4 bytes big-endian length][payload]

The flag's high bit (``0x80``) marks a *trailer* frame, whose payload is an
HTTP/1-style block of ``grpc-status`` / ``grpc-message`` headers. A ``0x00`` flag
marks a *data* frame, whose payload is a serialized protobuf message.

A server-streaming response is simply a concatenation of such frames, which the
HTTP layer may deliver split across arbitrary chunk boundaries — hence parsing is
an incremental state machine (:class:`GrpcWebFrameParser`) rather than a one-shot
decode. The C port keeps this same buffer-and-drain loop, swapping betterproto
for nanopb at the payload boundary only.
"""

from __future__ import annotations

import struct

DATA_FLAG = 0x00
TRAILER_FLAG = 0x80
HEADER_SIZE = 5


def encode_message(payload: bytes) -> bytes:
    """Wrap a serialized protobuf message in a single gRPC-Web data frame."""
    return struct.pack('>BI', DATA_FLAG, len(payload)) + payload


def is_trailer(flag: int) -> bool:
    """Return whether a frame flag marks a trailer (vs a data) frame."""
    return bool(flag & TRAILER_FLAG)


def parse_trailer(payload: bytes) -> dict[str, str]:
    """Parse a trailer frame body into a dict of lower-cased header names."""
    trailers: dict[str, str] = {}
    for line in payload.split(b'\r\n'):
        if not line:
            continue
        key, _, value = line.partition(b':')
        trailers[key.decode('ascii').strip().lower()] = value.decode('ascii').strip()
    return trailers


class GrpcWebFrameParser:
    """Incremental parser for a stream of gRPC-Web frames."""

    def __init__(self) -> None:
        """Start with an empty carry-over buffer."""
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[tuple[int, bytes]]:
        """Append ``data`` and return every frame now complete as (flag, payload)."""
        self._buffer.extend(data)
        frames: list[tuple[int, bytes]] = []
        while len(self._buffer) >= HEADER_SIZE:
            flag = self._buffer[0]
            (length,) = struct.unpack('>I', self._buffer[1:HEADER_SIZE])
            end = HEADER_SIZE + length
            if len(self._buffer) < end:
                break
            frames.append((flag, bytes(self._buffer[HEADER_SIZE:end])))
            del self._buffer[:end]
        return frames
