"""Tests for the Docker LAN-exposure toggle reducer behavior."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

DOCKER_SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app' / 'services' / '080-docker'


def _reducer_module() -> ModuleType:
    """Import the Docker reducer the way the service loader does.

    Every identity-sensitive symbol (the action/event classes the reducer
    matches against, ``CompleteReducerResult``, ``InitAction``) is read back off
    the returned module so the test always uses the same module generation as
    the reducer. Integration/flows tests earlier in the full suite churn
    ``sys.modules``; importing these classes at the top of this file instead
    would leave the test holding a stale generation, making the reducer's
    ``match`` / ``isinstance`` checks silently fall through to ``case _``.
    """
    docker_path = str(DOCKER_SERVICE_PATH)
    if docker_path not in sys.path:
        sys.path.insert(0, docker_path)
    try:
        return import_module('reducer')
    finally:
        if docker_path in sys.path:
            sys.path.remove(docker_path)


@pytest.fixture(autouse=True)
def _isolated_persistent_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep DockerServiceState's persistent-store reads off the real file."""
    store_path = tmp_path / 'state.json'
    monkeypatch.setattr('ubo_app.constants.PERSISTENT_STORE_PATH', store_path)
    monkeypatch.setattr(
        'ubo_app.utils.persistent_store.PERSISTENT_STORE_PATH',
        store_path,
    )


def test_set_expose_to_lan_updates_map_and_emits_rebind() -> None:
    """Setting exposure updates the map and emits a rebind event."""
    reducer_module = _reducer_module()
    service_reducer = reducer_module.service_reducer
    state = service_reducer(None, reducer_module.InitAction())

    result = service_reducer(
        state,
        reducer_module.DockerImageSetExposeToLanAction(
            image='ollama',
            expose_to_lan=True,
        ),
    )

    assert isinstance(result, reducer_module.CompleteReducerResult)
    assert result.state.expose_to_lan == {'ollama': True}
    assert any(
        isinstance(event, reducer_module.DockerImageRebindEvent)
        and event.image == 'ollama'
        for event in (result.events or [])
    )


def test_set_expose_to_lan_preserves_other_apps() -> None:
    """Toggling one app does not disturb another app's setting."""
    reducer_module = _reducer_module()
    service_reducer = reducer_module.service_reducer
    set_expose = reducer_module.DockerImageSetExposeToLanAction

    state = service_reducer(None, reducer_module.InitAction())
    state = service_reducer(
        state,
        set_expose(image='hermes', expose_to_lan=True),
    ).state
    result = service_reducer(
        state,
        set_expose(image='openclaw', expose_to_lan=False),
    )

    assert result.state.expose_to_lan == {'hermes': True, 'openclaw': False}
