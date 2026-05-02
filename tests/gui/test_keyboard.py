"""Tests for GUI client keyboard bindings."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import betterproto

from ubo_app.gui.ubo_gui_client import keyboard

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest
    from ubo_bindings.ubo.v1 import Action

    from ubo_app.gui.ubo_gui_client.client import GUIClient


class _FakeClient:
    def __init__(self) -> None:
        self.actions: list[Action] = []

    def dispatch_raw(self, action: Action) -> None:
        self.actions.append(action)


def test_v_key_repeat_dispatches_single_listening_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated key-down events only start listening once before key-up."""
    callbacks: dict[str, Callable[..., None]] = {}
    v_key = keyboard.Keyboard.keycodes['v']

    def bind(**kwargs: Callable[..., None]) -> None:
        callbacks.update(kwargs)

    def unbind(**kwargs: Callable[..., None]) -> None:
        for name, callback in kwargs.items():
            if callbacks.get(name) is callback:
                callbacks.pop(name)

    monkeypatch.setattr(keyboard.Window, 'bind', bind)
    monkeypatch.setattr(keyboard.Window, 'unbind', unbind)

    client = _FakeClient()
    cleanup = keyboard.setup_keyboard(cast('GUIClient', client))

    callbacks['on_key_down'](keyboard.Window, v_key, 0, 'v', [])
    callbacks['on_key_down'](keyboard.Window, v_key, 0, 'v', [])
    callbacks['on_key_down'](keyboard.Window, v_key, 0, 'v', [])
    callbacks['on_key_up'](keyboard.Window, v_key, 0)

    assert [
        betterproto.which_one_of(action, 'action')[0]
        for action in client.actions
    ] == [
        'assistant_start_listening_action',
        'assistant_stop_listening_action',
    ]

    for cleanup_callback in cleanup:
        cleanup_callback()
