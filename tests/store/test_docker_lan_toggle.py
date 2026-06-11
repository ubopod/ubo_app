"""Tests for the Docker LAN-exposure toggle reducer behavior."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from redux import CompleteReducerResult, InitAction

from ubo_app.store.services.docker import (
    DockerImageRebindEvent,
    DockerImageSetExposeToLanAction,
)

if TYPE_CHECKING:
    from collections.abc import Callable

DOCKER_SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app' / 'services' / '080-docker'


def _service_reducer() -> Callable:
    docker_path = str(DOCKER_SERVICE_PATH)
    if docker_path not in sys.path:
        sys.path.insert(0, docker_path)
    try:
        return cast('Callable', import_module('reducer').service_reducer)
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
    service_reducer = _service_reducer()
    state = service_reducer(None, InitAction())

    result = service_reducer(
        state,
        DockerImageSetExposeToLanAction(image='ollama', expose_to_lan=True),
    )

    assert isinstance(result, CompleteReducerResult)
    assert result.state.expose_to_lan == {'ollama': True}
    assert any(
        isinstance(event, DockerImageRebindEvent) and event.image == 'ollama'
        for event in (result.events or [])
    )


def test_set_expose_to_lan_preserves_other_apps() -> None:
    """Toggling one app does not disturb another app's setting."""
    service_reducer = _service_reducer()
    state = service_reducer(None, InitAction())

    state = service_reducer(
        state,
        DockerImageSetExposeToLanAction(image='hermes', expose_to_lan=True),
    ).state
    result = service_reducer(
        state,
        DockerImageSetExposeToLanAction(image='openclaw', expose_to_lan=False),
    )

    assert result.state.expose_to_lan == {'hermes': True, 'openclaw': False}
