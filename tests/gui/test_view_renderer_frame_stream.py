"""Tests for the frame-stream video subscription's lifetime.

The subscription belongs to the *stream*, not to the widget rendering it, and
`_render_view` tears it down on the way into every view. An in-place props
update for the stream already on screen returns before anything resubscribes,
so without care a `UpdateRenderPropsAction` aimed at a live feed freezes it —
silently, and only for the frame stream.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from ubo_bindings.ubo.v1 import MenuViewData, RenderViewData

# The GUI client is its own import root: its modules import each other as
# `ubo_gui_client.*`, which only resolves with `ubo_app/gui` on the path — the
# same arrangement the client's own entry point makes. The module is then
# reached through the package path, as `test_keyboard.py` does, so that static
# analysis can resolve it too.
_GUI_ROOT = str(Path(__file__).resolve().parents[2] / 'ubo_app' / 'gui')
if _GUI_ROOT not in sys.path:
    sys.path.insert(0, _GUI_ROOT)

from ubo_app.gui.ubo_gui_client.view_renderer import ViewRenderer  # noqa: E402


@pytest.fixture
def renderer() -> ViewRenderer:
    """Build a renderer with just enough wired up to exercise `_render_view`."""
    instance = ViewRenderer.__new__(ViewRenderer)
    instance._video_unsubscribe = None  # noqa: SLF001
    instance._last_render_stream_id = None  # noqa: SLF001
    return instance


def _render_view(stream_id: str, kind: str = 'frame_stream') -> RenderViewData:
    return RenderViewData(kind=kind, stream_id=stream_id)


def test_an_update_for_the_live_stream_keeps_its_subscription(
    renderer: ViewRenderer,
) -> None:
    """Otherwise the feed freezes on the frame it happened to be showing."""
    unsubscribed: list[bool] = []
    renderer._video_unsubscribe = lambda: unsubscribed.append(True)  # noqa: SLF001
    renderer._last_render_stream_id = 'camera'  # noqa: SLF001

    assert renderer._is_same_frame_stream(_render_view('camera')) is True  # noqa: SLF001
    assert unsubscribed == []


def test_a_different_stream_drops_the_subscription(renderer: ViewRenderer) -> None:
    """Opening another feed must not leave the previous one subscribed."""
    renderer._video_unsubscribe = lambda: None  # noqa: SLF001
    renderer._last_render_stream_id = 'camera'  # noqa: SLF001

    assert renderer._is_same_frame_stream(_render_view('doorbell')) is False  # noqa: SLF001


def test_another_render_kind_drops_the_subscription(renderer: ViewRenderer) -> None:
    """Only a frame stream owns a video subscription."""
    renderer._video_unsubscribe = lambda: None  # noqa: SLF001
    renderer._last_render_stream_id = 'camera'  # noqa: SLF001

    same = renderer._is_same_frame_stream(  # noqa: SLF001
        _render_view('camera', kind='readings'),
    )

    assert same is False


def test_navigating_to_a_menu_drops_the_subscription(renderer: ViewRenderer) -> None:
    """A view that is not a render view at all is a navigation away."""
    renderer._video_unsubscribe = lambda: None  # noqa: SLF001
    renderer._last_render_stream_id = 'camera'  # noqa: SLF001

    assert renderer._is_same_frame_stream(MenuViewData()) is False  # noqa: SLF001


def test_nothing_is_preserved_when_no_subscription_is_live(
    renderer: ViewRenderer,
) -> None:
    """Opening a frame stream for the first time must go down the rebuild path.

    Reporting "same stream" here would skip the very code that subscribes.
    """
    renderer._last_render_stream_id = 'camera'  # noqa: SLF001

    assert renderer._is_same_frame_stream(_render_view('camera')) is False  # noqa: SLF001
