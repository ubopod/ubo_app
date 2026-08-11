"""Tests for the per-app status projection on `DockerServiceState.apps`.

The web dashboard cannot read the per-image states directly — `combine_reducers`
synthesizes those as attributes on `DockerState`, and none of them exist in the
proto message, so packing the parent slice raises and kills the whole
`SubscribeStore` stream. `apps` is the serializable projection it reads instead.
"""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ubo_app.store.services.docker import (
    DockerAppStatus,
    DockerItemHealth,
    DockerItemStatus,
)

if TYPE_CHECKING:
    from types import ModuleType

DOCKER_SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app' / 'services' / '080-docker'


def _reducer_module() -> ModuleType:
    """Import the Docker reducer the way the service loader does."""
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


def _app(
    status: DockerItemStatus,
    health: DockerItemHealth = DockerItemHealth.OK,
) -> DockerAppStatus:
    return DockerAppStatus(
        id='home_assistant',
        label='Home Assistant',
        icon='󰟐',
        status=status,
        health=health,
    )


def test_reporting_an_installed_app_records_it() -> None:
    """An app with an image on the device shows up under its id."""
    reducer_module = _reducer_module()
    service_reducer = reducer_module.service_reducer
    state = service_reducer(None, reducer_module.InitAction())

    result = service_reducer(
        state,
        reducer_module.DockerSetAppStatusAction(
            app=_app(DockerItemStatus.RUNNING, DockerItemHealth.CRASH_LOOPING),
        ),
    )

    recorded = result.apps['home_assistant']
    assert recorded.label == 'Home Assistant'
    assert recorded.icon == '󰟐'
    assert recorded.status is DockerItemStatus.RUNNING
    # Health rides alongside the lifecycle status, never folded into it.
    assert recorded.health is DockerItemHealth.CRASH_LOOPING


def test_reporting_the_same_status_twice_keeps_the_state_object() -> None:
    """An unchanged report must not produce a new state.

    The dashboard's `SubscribeStore` autorun is keyed on this whole slice, so a
    no-op rewrite would push a frame to every connected client on every docker
    poll tick.
    """
    reducer_module = _reducer_module()
    service_reducer = reducer_module.service_reducer
    state = service_reducer(None, reducer_module.InitAction())
    action = reducer_module.DockerSetAppStatusAction(
        app=_app(DockerItemStatus.RUNNING),
    )

    first = service_reducer(state, action)
    second = service_reducer(first, action)

    assert second is first


def test_an_app_leaving_the_device_is_evicted() -> None:
    """`NOT_AVAILABLE` removes the row rather than storing an absent app.

    Images are never unregistered from the combine reducer, so falling back to
    `NOT_AVAILABLE` is the only signal a deleted app ever sends.
    """
    reducer_module = _reducer_module()
    service_reducer = reducer_module.service_reducer
    state = service_reducer(None, reducer_module.InitAction())

    installed = service_reducer(
        state,
        reducer_module.DockerSetAppStatusAction(app=_app(DockerItemStatus.AVAILABLE)),
    )
    removed = service_reducer(
        installed,
        reducer_module.DockerSetAppStatusAction(
            app=_app(DockerItemStatus.NOT_AVAILABLE),
        ),
    )

    assert 'home_assistant' in installed.apps
    assert removed.apps == {}


def test_an_app_that_was_never_installed_is_not_recorded() -> None:
    """A boot-time `NOT_AVAILABLE` report leaves the slice untouched."""
    reducer_module = _reducer_module()
    service_reducer = reducer_module.service_reducer
    state = service_reducer(None, reducer_module.InitAction())

    result = service_reducer(
        state,
        reducer_module.DockerSetAppStatusAction(
            app=_app(DockerItemStatus.NOT_AVAILABLE),
        ),
    )

    assert result is state


def test_image_reducer_ignores_the_projection_action() -> None:
    """It is a `DockerAction`, not a `DockerImageAction` — no image owns it."""
    reducer_module = _reducer_module()
    image_state = reducer_module.ImageState(
        id='home_assistant',
        label='Home Assistant',
        instructions=None,
    )

    result = reducer_module.image_reducer(
        image_state,
        reducer_module.DockerSetAppStatusAction(app=_app(DockerItemStatus.RUNNING)),
    )

    assert result is image_state
