"""Tests for the MCU-portable gRPC-Web framing codec."""

from __future__ import annotations

from ubo_lvgl_gui_client.grpc_web_frame import (
    DATA_FLAG,
    TRAILER_FLAG,
    GrpcWebFrameParser,
    encode_message,
    is_trailer,
    parse_trailer,
)


def test_encode_roundtrips_through_parser() -> None:
    """An encoded message decodes back to a single data frame."""
    payload = b'hello world'
    frames = GrpcWebFrameParser().feed(encode_message(payload))
    assert frames == [(DATA_FLAG, payload)]


def test_encode_empty_payload() -> None:
    """An empty payload still produces a well-formed data frame."""
    frames = GrpcWebFrameParser().feed(encode_message(b''))
    assert frames == [(DATA_FLAG, b'')]


def test_multiple_frames_in_one_feed() -> None:
    """Two back-to-back frames in one chunk are both parsed."""
    stream = encode_message(b'one') + encode_message(b'two')
    frames = GrpcWebFrameParser().feed(stream)
    assert frames == [(DATA_FLAG, b'one'), (DATA_FLAG, b'two')]


def test_frame_split_across_chunks() -> None:
    """A frame arriving in fragments is reassembled via the carry-over buffer."""
    stream = encode_message(b'abcdef')
    parser = GrpcWebFrameParser()
    # Split mid-header and mid-payload to exercise the carry-over buffer.
    assert parser.feed(stream[:2]) == []
    assert parser.feed(stream[2:7]) == []
    assert parser.feed(stream[7:]) == [(DATA_FLAG, b'abcdef')]


def test_trailer_frame_detected_and_parsed() -> None:
    """A trailer frame is flagged as such and its headers are parsed."""
    body = b'grpc-status:0\r\ngrpc-message:OK\r\n'
    frame = bytes([TRAILER_FLAG]) + len(body).to_bytes(4, 'big') + body
    frames = GrpcWebFrameParser().feed(frame)
    assert len(frames) == 1
    flag, payload = frames[0]
    assert is_trailer(flag)
    assert parse_trailer(payload) == {'grpc-status': '0', 'grpc-message': 'OK'}


def test_data_frame_not_trailer() -> None:
    """The data flag is not mistaken for a trailer."""
    assert not is_trailer(DATA_FLAG)
