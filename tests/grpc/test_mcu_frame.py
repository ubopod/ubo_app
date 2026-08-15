"""Unit tests for the MCU raw-TCP frame codec.

Pure codec tests — no server boot. These cross-check the same varint boundary
values (127/128/16383/16384) exercised by the future C test so the two encoders
stay byte-compatible.
"""

from __future__ import annotations

import asyncio

import pytest

from ubo_app.rpc.mcu_server import (
    DISPATCH_ACTION_REQUEST,
    DISPATCH_ACTION_RESPONSE,
    ERROR,
    MAX_FRAME_SIZE,
    PING,
    SUBSCRIBE_EVENT_REQUEST,
    SUBSCRIBE_EVENT_RESPONSE,
    SUBSCRIBE_STORE_REQUEST,
    SUBSCRIBE_STORE_RESPONSE,
    _encode_frame,
    _encode_varint,
    _read_frame,
    _read_varint,
)

ALL_MESSAGE_TYPES = [
    DISPATCH_ACTION_REQUEST,
    DISPATCH_ACTION_RESPONSE,
    SUBSCRIBE_STORE_REQUEST,
    SUBSCRIBE_STORE_RESPONSE,
    SUBSCRIBE_EVENT_REQUEST,
    SUBSCRIBE_EVENT_RESPONSE,
    ERROR,
    PING,
]

# 1-byte / 2-byte / 3-byte varint boundary lengths.
VARINT_BOUNDARIES = [0, 1, 127, 128, 16383, 16384]


def _make_reader(data: bytes) -> asyncio.StreamReader:
    """Build an in-memory StreamReader pre-fed with ``data`` and EOF."""
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


def test_message_type_constants_are_stable() -> None:
    """The wire discriminants must match the C header exactly."""
    assert DISPATCH_ACTION_REQUEST == 0x01
    assert DISPATCH_ACTION_RESPONSE == 0x02
    assert SUBSCRIBE_STORE_REQUEST == 0x03
    assert SUBSCRIBE_STORE_RESPONSE == 0x04
    assert SUBSCRIBE_EVENT_REQUEST == 0x05
    assert SUBSCRIBE_EVENT_RESPONSE == 0x06
    assert ERROR == 0x7E
    assert PING == 0x7F


@pytest.mark.parametrize('value', VARINT_BOUNDARIES)
async def test_varint_roundtrip(value: int) -> None:
    """Encoding then decoding a varint yields the original value."""
    encoded = _encode_varint(value)
    decoded = await _read_varint(_make_reader(encoded))
    assert decoded == value


def test_varint_boundary_widths() -> None:
    """Boundary values land on the expected varint byte widths."""
    assert len(_encode_varint(127)) == 1
    assert len(_encode_varint(128)) == 2
    assert len(_encode_varint(16383)) == 2
    assert len(_encode_varint(16384)) == 3


def test_encode_varint_rejects_negative() -> None:
    """Negative values are not encodable as varints."""
    with pytest.raises(ValueError, match='negative'):
        _encode_varint(-1)


async def test_decode_varint_rejects_truncated() -> None:
    """A varint whose continuation bit runs off the buffer is rejected."""
    with pytest.raises(asyncio.IncompleteReadError):
        await _read_varint(_make_reader(b'\x80'))


@pytest.mark.parametrize('message_type', ALL_MESSAGE_TYPES)
async def test_frame_roundtrip_each_message_type(message_type: int) -> None:
    """Every message type round-trips through encode → stream read."""
    payload = b'hello-mcu-payload'
    frame = _encode_frame(message_type, payload)
    reader = _make_reader(frame)

    read_type, read_payload = await _read_frame(reader)

    assert read_type == message_type
    assert read_payload == payload


async def test_frame_roundtrip_empty_payload() -> None:
    """An empty payload frames and reads back as empty bytes."""
    frame = _encode_frame(DISPATCH_ACTION_RESPONSE, b'')
    reader = _make_reader(frame)

    read_type, read_payload = await _read_frame(reader)

    assert read_type == DISPATCH_ACTION_RESPONSE
    assert read_payload == b''


@pytest.mark.parametrize('length', VARINT_BOUNDARIES)
async def test_frame_roundtrip_varint_length_boundaries(length: int) -> None:
    """Payloads at varint length boundaries survive a framing round-trip."""
    payload = bytes(length)
    frame = _encode_frame(SUBSCRIBE_STORE_RESPONSE, payload)
    reader = _make_reader(frame)

    read_type, read_payload = await _read_frame(reader)

    assert read_type == SUBSCRIBE_STORE_RESPONSE
    assert len(read_payload) == length
    assert read_payload == payload


async def test_read_frame_reassembles_partial_reads() -> None:
    """A frame delivered in dribs and drabs is reassembled correctly."""
    payload = bytes(200)  # 2-byte varint length header
    frame = _encode_frame(SUBSCRIBE_EVENT_RESPONSE, payload)

    reader = asyncio.StreamReader()
    read_task = asyncio.ensure_future(_read_frame(reader))

    # Feed one byte at a time, forcing the reader to await between bytes.
    for index in range(len(frame)):
        assert not read_task.done()
        reader.feed_data(frame[index : index + 1])
        await asyncio.sleep(0)

    read_type, read_payload = await read_task

    assert read_type == SUBSCRIBE_EVENT_RESPONSE
    assert read_payload == payload


async def test_read_frame_truncated_payload_raises() -> None:
    """A frame whose payload is cut short raises IncompleteReadError."""
    payload = b'not-fully-delivered'
    frame = _encode_frame(DISPATCH_ACTION_REQUEST, payload)
    reader = _make_reader(frame[:-3])  # drop the tail of the payload

    with pytest.raises(asyncio.IncompleteReadError):
        await _read_frame(reader)


async def test_read_frame_rejects_oversized_length() -> None:
    """A length header above the frame cap poisons the read."""
    header = bytes((SUBSCRIBE_STORE_REQUEST,)) + _encode_varint(MAX_FRAME_SIZE + 1)
    reader = _make_reader(header)

    with pytest.raises(ValueError, match='exceeds maximum'):
        await _read_frame(reader)


async def test_read_varint_rejects_non_terminating() -> None:
    """A varint with the continuation bit set forever is rejected."""
    reader = _make_reader(b'\x80' * 12)

    with pytest.raises(ValueError, match='non-terminating'):
        await _read_varint(reader)
