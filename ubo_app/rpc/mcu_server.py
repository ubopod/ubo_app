"""Lightweight raw-TCP listener for MCU/ESP32 clients ("tcp-lite").

This is a second, parallel transport that runs alongside the grpclib server in
``ubo_app/rpc/server.py``. It carries only three RPCs — ``DispatchAction``,
``SubscribeStore`` and ``SubscribeEvent`` — for a single trusted MCU peer,
bypassing Envoy/HTTP/grpc-web entirely. ``SecretsService`` is intentionally
never exposed on this path.

Wire format per frame::

    [1 byte message_type][varint length][protobuf payload]

``message_type`` is a hand-defined enum with no shared source of truth: the
constants below MUST stay byte-identical to the future C header
``ubo_lvgl/client/tcp_lite_frame.h`` (a later phase — it does not exist yet).
This is the same manual-sync caveat that applies to the curated proto oneof
tags described in ``.claude/skills/lvgl-maintenance/SKILL.md``.

Phase 1 is plaintext and unauthenticated by explicit decision — no Noise, no
encryption. The listener binds ``0.0.0.0`` directly in-process, following the
precedent of ``MCP_GATEWAY_LISTEN_ADDRESS``.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
from typing import TYPE_CHECKING, cast

from ubo_app.constants import MCU_LISTEN_ADDRESS, MCU_LISTEN_PORT
from ubo_app.logger import logger
from ubo_app.rpc.store_service import StoreService

from ubo_bindings.store.v1 import (
    DispatchActionRequest,
    SubscribeEventRequest,
    SubscribeStoreRequest,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    import betterproto

# Message-type discriminants. Keep byte-identical to the C header
# ``ubo_lvgl/client/tcp_lite_frame.h`` — there is no shared source of truth.
DISPATCH_ACTION_REQUEST = 0x01
DISPATCH_ACTION_RESPONSE = 0x02
SUBSCRIBE_STORE_REQUEST = 0x03
SUBSCRIBE_STORE_RESPONSE = 0x04
SUBSCRIBE_EVENT_REQUEST = 0x05
SUBSCRIBE_EVENT_RESPONSE = 0x06
ERROR = 0x7E  # reserved
PING = 0x7F  # reserved (future keepalive)

# Same cap/rationale as ``UBO_GRPC_WEB_MAX_FRAME`` on the C side.
MAX_FRAME_SIZE = 1 << 20

# Poison a varint whose continuation bit is still set past this many shifted
# bits — a malformed, non-terminating length header.
_VARINT_MAX_SHIFT = 64

_server_container: list[asyncio.Server | None] = [None]


def _encode_varint(value: int) -> bytes:
    """Encode a non-negative integer as a base-128 varint."""
    if value < 0:
        msg = 'Cannot encode a negative value as a varint'
        raise ValueError(msg)
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            result.append(byte | 0x80)
        else:
            result.append(byte)
            return bytes(result)


def _encode_frame(message_type: int, payload: bytes) -> bytes:
    """Frame a payload as ``[message_type][varint length][payload]``."""
    return bytes((message_type,)) + _encode_varint(len(payload)) + payload


async def _read_exact(reader: asyncio.StreamReader, count: int) -> bytes:
    """Read exactly ``count`` bytes, transparently handling partial reads."""
    return await reader.readexactly(count)


async def _read_varint(reader: asyncio.StreamReader) -> int:
    """Read a base-128 varint from the stream, one byte at a time."""
    result = 0
    shift = 0
    while True:
        byte = (await _read_exact(reader, 1))[0]
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result
        shift += 7
        if shift >= _VARINT_MAX_SHIFT:
            msg = 'Varint too long (non-terminating)'
            raise ValueError(msg)


async def _read_frame(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    """Read one ``[message_type][varint length][payload]`` frame."""
    message_type = (await _read_exact(reader, 1))[0]
    length = await _read_varint(reader)
    if length > MAX_FRAME_SIZE:
        msg = f'Frame length {length} exceeds maximum {MAX_FRAME_SIZE}'
        raise ValueError(msg)
    payload = await _read_exact(reader, length)
    return message_type, payload


async def _write_message(
    writer: asyncio.StreamWriter,
    message_type: int,
    message: betterproto.Message,
) -> None:
    """Serialize and write a framed protobuf message, then flush."""
    writer.write(_encode_frame(message_type, message.SerializeToString()))
    await writer.drain()


async def _serve_dispatch_action(
    payload: bytes,
    writer: asyncio.StreamWriter,
) -> None:
    """One-shot dispatch: request → one response frame → close."""
    request = DispatchActionRequest().parse(payload)
    response = await StoreService().dispatch_action(request)
    await _write_message(writer, DISPATCH_ACTION_RESPONSE, response)


async def _serve_subscribe_store(
    payload: bytes,
    writer: asyncio.StreamWriter,
) -> None:
    """Stream store snapshots until the client disconnects."""
    request = SubscribeStoreRequest().parse(payload)
    agen = cast(
        'AsyncGenerator[betterproto.Message, None]',
        StoreService().subscribe_store(request),
    )
    try:
        async for response in agen:
            await _write_message(writer, SUBSCRIBE_STORE_RESPONSE, response)
    finally:
        # Close the generator synchronously so the store autorun is
        # unsubscribed on disconnect rather than waiting on asyncgen GC.
        await agen.aclose()


async def _serve_subscribe_event(
    payload: bytes,
    writer: asyncio.StreamWriter,
) -> None:
    """Stream events until the client disconnects."""
    request = SubscribeEventRequest().parse(payload)
    agen = cast(
        'AsyncGenerator[betterproto.Message, None]',
        StoreService().subscribe_event(request),
    )
    try:
        async for response in agen:
            await _write_message(writer, SUBSCRIBE_EVENT_RESPONSE, response)
    finally:
        # Synchronous unsubscription on disconnect (see above).
        await agen.aclose()


async def _handle_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    """Read the first frame and dispatch to the matching RPC handler."""
    # SubscribeStore/SubscribeEvent hold a store subscription open for as long
    # as the peer stays connected; a vanished (half-open) MCU is otherwise only
    # detected on the next failed write, which subscribe_event's idle gaps can
    # delay indefinitely. Let the OS reap dead peers instead.
    sock = writer.get_extra_info('socket')
    if sock is not None:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    try:
        message_type, payload = await _read_frame(reader)
        if message_type == DISPATCH_ACTION_REQUEST:
            await _serve_dispatch_action(payload, writer)
        elif message_type == SUBSCRIBE_STORE_REQUEST:
            await _serve_subscribe_store(payload, writer)
        elif message_type == SUBSCRIBE_EVENT_REQUEST:
            await _serve_subscribe_event(payload, writer)
        else:
            logger.warning(
                'Unknown MCU message type',
                extra={'message_type': message_type},
            )
    except (asyncio.IncompleteReadError, ConnectionError, OSError):
        logger.debug('MCU client disconnected', exc_info=True)
    except Exception:  # noqa: BLE001 -- unauthenticated listener: a malformed
        # frame (poisoned varint, oversized length, bad protobuf) must never
        # escape as an unhandled exception in asyncio's callback.
        logger.warning('Dropping malformed MCU frame', exc_info=True)
    finally:
        writer.close()
        with contextlib.suppress(asyncio.IncompleteReadError, ConnectionError, OSError):
            await writer.wait_closed()


def get_server() -> asyncio.Server | None:
    """Get the current MCU server instance."""
    return _server_container[0]


async def close_server() -> None:
    """Close the MCU server if running."""
    server = _server_container[0]
    if server is not None:
        server.close()
        await server.wait_closed()
        _server_container[0] = None


async def serve() -> None:
    """Serve the MCU raw-TCP listener."""
    server = await asyncio.start_server(
        _handle_connection,
        MCU_LISTEN_ADDRESS,
        MCU_LISTEN_PORT,
    )
    _server_container[0] = server

    logger.info(
        'Starting MCU server',
        extra={'host': MCU_LISTEN_ADDRESS, 'port': MCU_LISTEN_PORT},
    )
    async with server:
        await server.serve_forever()
