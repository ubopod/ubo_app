"""Tests for `register_persistent_store`'s contract.

It used to return `None`, so a service had nothing to return from
`init_service()`'s subscriptions: every restart left another autorun behind,
holding a selector over an unloaded module and a coroutine runner bound to a
stopped loop — and still writing to `state.json`.

The autorun itself is driven through a store double rather than the real store,
which would need a worker thread and an event loop to run its async reaction.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from ubo_app.utils.persistent_store import (
    read_from_persistent_store,
    register_persistent_store,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def _stored() -> dict[str, Any]:
    """Read back the isolated `state.json` the conftest fixture points at."""
    import ubo_app.constants

    return json.loads(Path(ubo_app.constants.PERSISTENT_STORE_PATH).read_text())


class _Autorun:
    """Stands in for what `store.autorun` returns."""

    def __init__(self, reaction: Callable[..., Any]) -> None:
        self.reaction = reaction
        self.unsubscribed = False

    def unsubscribe(self) -> None:
        self.unsubscribed = True


class _RecordingStore:
    """Records the autorun instead of subscribing it to a real store."""

    def __init__(self) -> None:
        self.autoruns: list[_Autorun] = []

    def autorun(self, _selector: Callable[..., Any]) -> Callable[..., _Autorun]:
        def _decorate(reaction: Callable[..., Any]) -> _Autorun:
            autorun = _Autorun(reaction)
            self.autoruns.append(autorun)
            return autorun

        return _decorate

    def serialize_value(self, value: object) -> object:
        return value


@pytest.fixture
def recording_store(monkeypatch: pytest.MonkeyPatch) -> _RecordingStore:
    """Swap the real store out; `register_persistent_store` imports it lazily."""
    import ubo_app.store.main

    store = _RecordingStore()
    monkeypatch.setattr(ubo_app.store.main, 'store', store)
    return store


def test_it_returns_the_autoruns_unsubscribe(
    recording_store: _RecordingStore,
) -> None:
    """What a service returns from `init_service`'s subscriptions.

    A `None` here is what left a listener behind on every service restart.
    """
    unsubscribe = register_persistent_store('test_key', lambda state: state)

    (autorun,) = recording_store.autoruns
    assert unsubscribe == autorun.unsubscribe

    unsubscribe()
    assert autorun.unsubscribed is True


async def test_the_registered_reaction_writes_the_selector_value(
    recording_store: _RecordingStore,
) -> None:
    """The other half of the contract: it does write while it is subscribed."""
    register_persistent_store('test_key', lambda state: state)
    (autorun,) = recording_store.autoruns

    await autorun.reaction('a value')

    stored = _stored()
    assert stored['test_key'] == 'a value'
    # And the rest of the document survives the update.
    assert len(stored) > 1


async def test_a_none_value_writes_nothing(
    recording_store: _RecordingStore,
) -> None:
    """`None` means "no value yet"; `False` and `0` are values and must persist.

    The check is `is None` rather than falsiness for exactly that reason — the
    MQTT service persists an `is_enabled` of `False`.
    """
    register_persistent_store('test_key', lambda state: state)
    (autorun,) = recording_store.autoruns

    await autorun.reaction(None)
    assert 'test_key' not in _stored()

    await autorun.reaction(value=False)
    assert _stored()['test_key'] is False


async def test_a_write_preserves_the_store_files_permissions(
    recording_store: _RecordingStore,
) -> None:
    """Updating shared state must not replace its inode metadata."""
    import ubo_app.constants

    register_persistent_store('test_key', lambda state: state)
    (autorun,) = recording_store.autoruns
    store_path = Path(ubo_app.constants.PERSISTENT_STORE_PATH)
    store_path.chmod(0o600)

    await autorun.reaction('a value')

    assert store_path.stat().st_mode & 0o777 == 0o600
    assert _stored()['test_key'] == 'a value'


def test_reading_back_a_missing_key_uses_the_default() -> None:
    """The read side is unchanged; pinned here because the write side moved."""
    assert read_from_persistent_store('no_such_key', default='fallback') == 'fallback'
