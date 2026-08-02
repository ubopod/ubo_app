"""Low-res RGB565 row chunks of frame streams for constrained clients.

Memory-constrained clients (the ESP32 LVGL client has ~50KB free heap)
cannot decode a full-res RGB888 frame event (240x240x3 = ~173KB), the same
way they cannot decode large audio frames (see `_MAX_AUDIO_CHUNK_BYTES` in
the assistant's `ubo_output_transport`). Producers of `FrameStreamDataEvent`
call `low_res_chunk_events` to additionally emit a downsampled RGB565
little-endian companion stream, split into whole-row chunks small enough to
decode on such clients, throttled to `LOW_RES_FPS`.

Stills (`register_still`) go through the same path but need retention: a
camera re-pushes a frame every `VIEWFINDER_INTERVAL`, so a client that joins
late self-heals within one frame period, whereas a still has no next frame.
The retained picture is deliberately kept here rather than in Redux state --
state is broadcast to every client, which is exactly what makes an inline
multi-megabyte image knock the MCU clients off the air.
"""

from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

import numpy as np

from ubo_app.store.core.types import FrameStreamChunkEvent

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ubo_app.store.core.types import FrameStreamDataEvent, StackChangedEvent
    from ubo_app.store.core.types.stack_items import StackItemType

LOW_RES_MAX_DIM = 120
LOW_RES_FPS = 10
LOW_RES_CHUNK_BYTES = 8192

_last_dispatch_times: dict[str, float] = {}

_stills: dict[str, tuple[bytes, int, int]] = {}
_open_stream_ids: set[str] = set()
_stack_subscription: list[Callable[[], None]] = []


def low_res_chunk_events(
    stream_id: str,
    data: bytes,
    width: int,
    height: int,
    *,
    force: bool = False,
) -> list[FrameStreamChunkEvent]:
    """Downsample an RGB888 frame into RGB565-LE row-chunk events.

    Returns `[]` when called more often than `LOW_RES_FPS` for the same
    `stream_id`, so producers can call it for every full-res frame.

    Pass ``force=True`` for a STILL image. Throttling assumes a next frame is
    coming: for a camera a dropped frame costs 100ms, but a still that gets
    throttled is lost outright and the view stays blank forever.
    """
    if width <= 0 or height <= 0 or len(data) < width * height * 3:
        return []

    now = time.monotonic()
    if not force:
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


def register_still(stream_id: str, data: bytes, width: int, height: int) -> None:
    """Retain a still image for `stream_id`, to be emitted when its view opens.

    Emitting on open is what makes a *deferred* producer possible: the file
    browser builds its "Open Image" action when the notification is created,
    long before the user picks it, and by then the producer is no longer in the
    loop. It also means registering costs nothing on the wire until someone
    actually looks -- browsing a directory of images must not broadcast one
    multi-megabyte event per file.

    Registering while the view is already open (the assistant replacing its
    picture in place) emits immediately, since no stack change follows.
    """
    _stills[stream_id] = (data, width, height)
    _ensure_stack_subscription()
    _emit_still_if_open(stream_id)


def forget_still(stream_id: str) -> None:
    """Drop the retained still for `stream_id`."""
    _stills.pop(stream_id, None)


def forget_stream(stream_id: str) -> None:
    """Drop throttling state for a stream that has closed.

    ``_last_dispatch_times`` is keyed by ``stream_id`` and never expires; a
    long-lived process that shows many one-shot images would otherwise
    accumulate an entry per image.
    """
    _last_dispatch_times.pop(stream_id, None)


def open_still_events() -> list[FrameStreamDataEvent | FrameStreamChunkEvent]:
    """Frame events replaying every retained still whose view is on the stack.

    Replayed to each newly subscribed client, exactly like the initial view and
    stack (see `ubo_app/rpc/store_service.py:_send_initial_state`). Without it a
    client that connects -- or a satellite that reboots -- while a picture is on
    screen would render the `image_viewer` view forever without ever receiving
    the pixels: the emission happened when the view opened, and a still has no
    next frame. It also removes the race in which a rich client subscribes to
    the frame stream only *after* rendering the view.
    """
    from ubo_app.store.core.types.stack_items import RenderStackItem
    from ubo_app.store.main import store

    @store.with_state(lambda state: state.main.stack)
    def _collect(
        stack: Sequence[StackItemType],
    ) -> list[FrameStreamDataEvent | FrameStreamChunkEvent]:
        events: list[FrameStreamDataEvent | FrameStreamChunkEvent] = []
        for item in stack:
            if isinstance(item, RenderStackItem) and item.stream_id in _stills:
                events.extend(_still_events(item.stream_id))
        return events

    return _collect()


def _still_events(
    stream_id: str,
) -> list[FrameStreamDataEvent | FrameStreamChunkEvent]:
    """Full-res event plus its low-res companion for a retained still."""
    still = _stills.get(stream_id)
    if still is None:
        return []
    from ubo_app.store.core.types import FrameStreamDataEvent

    data, width, height = still
    return [
        FrameStreamDataEvent(
            stream_id=stream_id,
            data=data,
            width=width,
            height=height,
        ),
        # force=True: a throttled still is lost outright rather than merely
        # delayed, and the view would stay blank forever.
        *low_res_chunk_events(stream_id, data, width, height, force=True),
    ]


def _emit_still(stream_id: str) -> None:
    """Dispatch the retained still for `stream_id` as frame-stream events."""
    events = _still_events(stream_id)
    if not events:
        return
    from ubo_app.store.main import store

    store._dispatch(events)  # noqa: SLF001


def _emit_still_if_open(stream_id: str) -> None:
    """Emit the retained still only while its render view is on the stack."""
    if stream_id in _open_stream_ids:
        _emit_still(stream_id)


def _handle_stack_changed(event: StackChangedEvent) -> None:
    """Emit retained stills for render views that just opened."""
    from ubo_app.store.core.types.stack_items import RenderStackItem

    current = {
        item.stream_id
        for item in event.stack
        if isinstance(item, RenderStackItem) and item.stream_id
    }
    opened = current - _open_stream_ids
    closed = _open_stream_ids - current
    _open_stream_ids.clear()
    _open_stream_ids.update(current)

    for stream_id in closed:
        forget_stream(stream_id)
    for stream_id in opened & _stills.keys():
        _emit_still(stream_id)


def _ensure_stack_subscription() -> None:
    """Subscribe to stack changes once, on the first retained still."""
    if _stack_subscription:
        return
    from ubo_app.store.core.types import StackChangedEvent
    from ubo_app.store.main import store

    _stack_subscription.append(
        store.subscribe_event(StackChangedEvent, _handle_stack_changed),
    )
