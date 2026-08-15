"""Tests for still-image retention in `ubo_app.utils.frame_stream`.

A camera re-pushes a frame every `VIEWFINDER_INTERVAL`, so a client that
subscribes late self-heals within one frame period. A still has no next frame,
which is why the picture is retained and re-emitted whenever the render view
carrying its `stream_id` opens -- and why the file browser can build its "Open
Image" action long before the user picks it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ubo_app.store.core.types import (
    FrameStreamChunkEvent,
    FrameStreamDataEvent,
    StackChangedEvent,
)
from ubo_app.store.core.types.stack_items import MenuStackItem, RenderStackItem
from ubo_app.utils import frame_stream

if TYPE_CHECKING:
    from redux import BaseEvent

STREAM_ID = 'test:image'
WIDTH = 8
HEIGHT = 4
IMAGE = bytes([7]) * (WIDTH * HEIGHT * 3)


@pytest.fixture
def dispatched(monkeypatch: pytest.MonkeyPatch) -> list[BaseEvent]:
    """Collect events instead of dispatching, with no timers and no store."""
    from ubo_app.store.main import store

    events: list[BaseEvent] = []
    monkeypatch.setattr(store, '_dispatch', events.extend)
    # Pretend the stack subscription is already in place: this is a unit test
    # of the handler, not of the store's event plumbing.
    monkeypatch.setattr(frame_stream, '_stack_subscription', [lambda: None])
    monkeypatch.setattr(frame_stream, '_stills', {})
    monkeypatch.setattr(frame_stream, '_open_stream_ids', set())
    monkeypatch.setattr(frame_stream, '_last_dispatch_times', {})
    return events


def _open(*stream_ids: str) -> None:
    """Feed a stack whose render views carry `stream_ids`."""
    frame_stream._handle_stack_changed(  # noqa: SLF001
        StackChangedEvent(
            stack=(
                MenuStackItem(id='menu', menu_key=''),
                *(
                    RenderStackItem(id=f'r-{i}', kind='image_viewer', stream_id=s)
                    for i, s in enumerate(stream_ids)
                ),
            ),
        ),
    )


def test_registering_a_still_does_not_put_it_on_the_wire(
    dispatched: list[BaseEvent],
) -> None:
    """Browsing a directory of images must not broadcast one event per file."""
    frame_stream.register_still(STREAM_ID, IMAGE, WIDTH, HEIGHT)

    assert dispatched == []


def test_still_is_emitted_when_its_view_opens(dispatched: list[BaseEvent]) -> None:
    """The deferred producer's picture arrives when the user asks for it."""
    frame_stream.register_still(STREAM_ID, IMAGE, WIDTH, HEIGHT)

    _open(STREAM_ID)

    full = [event for event in dispatched if isinstance(event, FrameStreamDataEvent)]
    assert len(full) == 1
    assert full[0].stream_id == STREAM_ID
    assert full[0].data == IMAGE
    assert (full[0].width, full[0].height) == (WIDTH, HEIGHT)
    # The MCU clients read the downsampled companion stream, not the full-res
    # event, so both have to be emitted.
    chunks = [event for event in dispatched if isinstance(event, FrameStreamChunkEvent)]
    assert chunks
    assert all(chunk.stream_id == STREAM_ID for chunk in chunks)


def test_still_is_re_emitted_every_time_the_view_reopens(
    dispatched: list[BaseEvent],
) -> None:
    """A client that reconnects, or a user who backs out and returns, sees it."""
    frame_stream.register_still(STREAM_ID, IMAGE, WIDTH, HEIGHT)

    _open(STREAM_ID)
    _open()  # backed out
    _open(STREAM_ID)  # opened again

    full = [event for event in dispatched if isinstance(event, FrameStreamDataEvent)]
    assert len(full) == 2


def test_staying_on_the_stack_does_not_re_emit(dispatched: list[BaseEvent]) -> None:
    """Only the absent -> present edge emits; unrelated stack churn does not."""
    frame_stream.register_still(STREAM_ID, IMAGE, WIDTH, HEIGHT)

    _open(STREAM_ID)
    _open(STREAM_ID, 'other:stream')

    full = [event for event in dispatched if isinstance(event, FrameStreamDataEvent)]
    assert len(full) == 1


def test_replacing_the_picture_while_open_emits_immediately(
    dispatched: list[BaseEvent],
) -> None:
    """The assistant replaces its image in place, so no stack change follows."""
    frame_stream.register_still(STREAM_ID, IMAGE, WIDTH, HEIGHT)
    _open(STREAM_ID)
    dispatched.clear()

    replacement = bytes([9]) * (WIDTH * HEIGHT * 3)
    frame_stream.register_still(STREAM_ID, replacement, WIDTH, HEIGHT)

    full = [event for event in dispatched if isinstance(event, FrameStreamDataEvent)]
    assert len(full) == 1
    assert full[0].data == replacement


def test_forgotten_still_is_not_emitted(dispatched: list[BaseEvent]) -> None:
    """Nothing is retained for a stream nobody registered."""
    frame_stream.register_still(STREAM_ID, IMAGE, WIDTH, HEIGHT)
    frame_stream.forget_still(STREAM_ID)

    _open(STREAM_ID)

    assert dispatched == []


def test_open_stills_are_replayed_to_a_new_subscriber(
    dispatched: list[BaseEvent],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A client connecting mid-view gets the picture it would otherwise miss.

    This is what makes a rebooted satellite render the image that was already
    on screen -- the stack does not change, so nothing else would emit it.
    """
    _ = dispatched
    from ubo_app.store.main import store

    frame_stream.register_still(STREAM_ID, IMAGE, WIDTH, HEIGHT)
    stack = (
        MenuStackItem(id='menu', menu_key=''),
        RenderStackItem(id='r', kind='image_viewer', stream_id=STREAM_ID),
    )
    monkeypatch.setattr(
        store,
        'with_state',
        lambda _selector: lambda fn: lambda: fn(stack),
    )

    replayed = frame_stream.open_still_events()

    full = [event for event in replayed if isinstance(event, FrameStreamDataEvent)]
    assert len(full) == 1
    assert full[0].data == IMAGE
    assert any(isinstance(event, FrameStreamChunkEvent) for event in replayed)


def test_closing_a_stream_prunes_its_throttle_state(
    dispatched: list[BaseEvent],
) -> None:
    """Leaving the stack is the signal that a stream's throttle entry is dead."""
    _ = dispatched
    frame_stream.register_still(STREAM_ID, IMAGE, WIDTH, HEIGHT)
    _open(STREAM_ID)
    assert STREAM_ID in frame_stream._last_dispatch_times  # noqa: SLF001

    _open()

    assert STREAM_ID not in frame_stream._last_dispatch_times  # noqa: SLF001
