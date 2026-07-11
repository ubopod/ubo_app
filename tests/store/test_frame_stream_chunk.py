"""Tests for the low-res frame-stream chunk helper.

Covers downsample dimensions, RGB565-LE packing, whole-row chunk math, and
per-stream throttling in `ubo_app.utils.frame_stream.low_res_chunk_events`.
"""

from __future__ import annotations

import numpy as np
import pytest

from ubo_app.utils import frame_stream
from ubo_app.utils.frame_stream import (
    LOW_RES_CHUNK_BYTES,
    LOW_RES_MAX_DIM,
    low_res_chunk_events,
)


@pytest.fixture(autouse=True)
def _reset_throttle() -> None:
    frame_stream._last_dispatch_times.clear()  # noqa: SLF001


def _solid_frame(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    return bytes(rgb) * (width * height)


@pytest.mark.parametrize(
    ('width', 'height', 'expected'),
    [
        (240, 240, (120, 120)),
        (240, 136, (120, 68)),
        (120, 120, (120, 120)),
        (100, 60, (100, 60)),
    ],
)
def test_downsample_dimensions(
    width: int,
    height: int,
    expected: tuple[int, int],
) -> None:
    """Downsampled dims fit LOW_RES_MAX_DIM and preserve aspect."""
    frame = _solid_frame(width, height, (0, 0, 0))
    events = low_res_chunk_events('s', frame, width, height)
    assert events
    assert all((event.width, event.height) == expected for event in events)
    assert all(event.width <= LOW_RES_MAX_DIM for event in events)


@pytest.mark.parametrize(
    ('rgb', 'expected_le'),
    [
        ((255, 0, 0), b'\x00\xf8'),
        ((0, 255, 0), b'\xe0\x07'),
        ((0, 0, 255), b'\x1f\x00'),
        ((255, 255, 255), b'\xff\xff'),
        ((0, 0, 0), b'\x00\x00'),
    ],
)
def test_rgb565_little_endian_packing(
    rgb: tuple[int, int, int],
    expected_le: bytes,
) -> None:
    """Known colors pack to the expected RGB565-LE bytes."""
    events = low_res_chunk_events('s', _solid_frame(240, 240, rgb), 240, 240)
    assert events[0].data[:2] == expected_le


def test_chunk_math() -> None:
    """Chunks are whole rows, within size cap, contiguous, and complete."""
    events = low_res_chunk_events('s', _solid_frame(240, 240, (1, 2, 3)), 240, 240)

    row_bytes = events[0].width * 2
    next_row = 0
    for event in events:
        assert len(event.data) <= LOW_RES_CHUNK_BYTES
        assert len(event.data) % row_bytes == 0
        assert event.row_offset == next_row
        next_row += len(event.data) // row_bytes
    assert next_row == events[0].height

    total = sum(len(event.data) for event in events)
    assert total == events[0].width * events[0].height * 2


def test_pixel_values_survive_downsample() -> None:
    """Spatial content survives the stride downsample."""
    # Left half red, right half blue, at full resolution.
    frame = np.zeros((240, 240, 3), dtype=np.uint8)
    frame[:, :120, 0] = 255
    frame[:, 120:, 2] = 255

    events = low_res_chunk_events('s', frame.tobytes(), 240, 240)
    first_row = events[0].data[: events[0].width * 2]
    assert first_row[:2] == b'\x00\xf8'  # red
    assert first_row[-2:] == b'\x1f\x00'  # blue


def test_throttle_per_stream() -> None:
    """Rapid consecutive calls are throttled per stream id."""
    frame = _solid_frame(240, 240, (0, 0, 0))
    assert low_res_chunk_events('a', frame, 240, 240)
    assert low_res_chunk_events('a', frame, 240, 240) == []
    # An independent stream is not throttled by stream 'a'.
    assert low_res_chunk_events('b', frame, 240, 240)


def test_invalid_input_returns_no_events() -> None:
    """Empty or malformed frames yield no events."""
    assert low_res_chunk_events('s', b'', 240, 240) == []
    assert low_res_chunk_events('s', _solid_frame(240, 240, (0, 0, 0)), 0, 240) == []
