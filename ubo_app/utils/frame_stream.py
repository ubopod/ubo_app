"""Low-res RGB565 row chunks of frame streams for constrained clients.

Memory-constrained clients (the ESP32 LVGL client has ~50KB free heap)
cannot decode a full-res RGB888 frame event (240x240x3 = ~173KB), the same
way they cannot decode large audio frames (see `_MAX_AUDIO_CHUNK_BYTES` in
the assistant's `ubo_output_transport`). Producers of `FrameStreamDataEvent`
call `low_res_chunk_events` to additionally emit a downsampled RGB565
little-endian companion stream, split into whole-row chunks small enough to
decode on such clients, throttled to `LOW_RES_FPS`.
"""

from __future__ import annotations

import math
import time

import numpy as np

from ubo_app.store.core.types import FrameStreamChunkEvent

LOW_RES_MAX_DIM = 120
LOW_RES_FPS = 10
LOW_RES_CHUNK_BYTES = 8192

_last_dispatch_times: dict[str, float] = {}


def low_res_chunk_events(
    stream_id: str,
    data: bytes,
    width: int,
    height: int,
) -> list[FrameStreamChunkEvent]:
    """Downsample an RGB888 frame into RGB565-LE row-chunk events.

    Returns `[]` when called more often than `LOW_RES_FPS` for the same
    `stream_id`, so producers can call it for every full-res frame.
    """
    if width <= 0 or height <= 0 or len(data) < width * height * 3:
        return []

    now = time.monotonic()
    last = _last_dispatch_times.get(stream_id)
    if last is not None and now - last < 1 / LOW_RES_FPS:
        return []
    _last_dispatch_times[stream_id] = now

    step = max(1, math.ceil(max(width, height) / LOW_RES_MAX_DIM))
    frame = (
        np.frombuffer(data, dtype=np.uint8)[: width * height * 3]
        .reshape(height, width, 3)
        .astype(np.uint16)[::step, ::step]
    )
    out_height, out_width = frame.shape[:2]

    rgb565 = (
        ((frame[:, :, 0] & 0xF8) << 8)
        | ((frame[:, :, 1] & 0xFC) << 3)
        | (frame[:, :, 2] >> 3)
    )
    payload = rgb565.astype('<u2').tobytes()

    row_bytes = out_width * 2
    rows_per_chunk = max(1, LOW_RES_CHUNK_BYTES // row_bytes)
    return [
        FrameStreamChunkEvent(
            stream_id=stream_id,
            data=payload[row * row_bytes : (row + rows_per_chunk) * row_bytes],
            width=out_width,
            height=out_height,
            row_offset=row,
        )
        for row in range(0, out_height, rows_per_chunk)
    ]
