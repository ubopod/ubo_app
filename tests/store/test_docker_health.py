"""Tests for Docker crash detection.

Every container ubo creates carries ``restart_policy: always``, so a crash is
undone by a restart within seconds. These assert the two things that makes
tricky: that a crash is still visible afterwards, and that a deliberate stop is
never mistaken for one.
"""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ubo_app.store.services.docker import (
    CRASH_LOOP_THRESHOLD,
    CRASH_LOOP_WINDOW,
    DockerItemHealth,
    DockerItemStatus,
    ImageState,
    derive_health,
)

if TYPE_CHECKING:
    from types import ModuleType

DOCKER_SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app' / 'services' / '080-docker'

NOW = 1_000_000.0


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


def _image(**kwargs: object) -> ImageState:
    """Build a *running* app; health only describes one meant to be up."""
    kwargs.setdefault('status', DockerItemStatus.RUNNING)
    return ImageState(id='app', label='App', instructions=None, **kwargs)  # pyright: ignore[reportArgumentType]


def test_untouched_app_is_healthy() -> None:
    """No restarts, nothing to report."""
    assert derive_health(_image(), now=NOW) is DockerItemHealth.OK


def test_deliberate_stop_is_not_a_crash() -> None:
    """`container.stop()` is SIGTERM then SIGKILL, so a clean stop exits 143.

    The exit code alone would read as a crash. Only the restart policy moves
    ``restart_count``, and a user-initiated stop does not.
    """
    stopped = _image(last_exit_code=143, last_exit_at=NOW - 1)

    assert derive_health(stopped, now=NOW) is DockerItemHealth.OK


def test_single_restart_reads_as_recovered() -> None:
    """It went down and came back on its own — worth saying, not an alarm."""
    recovered = _image(restart_count=1, last_exit_code=1, last_exit_at=NOW - 1)

    assert derive_health(recovered, now=NOW) is DockerItemHealth.RECOVERED


def test_repeated_recent_restarts_read_as_crash_looping() -> None:
    """Enough restarts, recently enough, and it cannot stay up."""
    looping = _image(
        restart_count=CRASH_LOOP_THRESHOLD,
        last_exit_code=1,
        last_exit_at=NOW - 1,
    )

    assert derive_health(looping, now=NOW) is DockerItemHealth.CRASH_LOOPING


def test_old_restarts_do_not_read_as_crash_looping() -> None:
    """`restart_count` is cumulative since the last manual start.

    An app up for weeks with a handful of long-ago restarts is healthy, so the
    window is what keeps the count from becoming a permanent alarm.
    """
    settled = _image(
        restart_count=CRASH_LOOP_THRESHOLD * 10,
        last_exit_code=1,
        last_exit_at=NOW - CRASH_LOOP_WINDOW - 1,
    )

    assert derive_health(settled, now=NOW) is DockerItemHealth.RECOVERED


def test_report_exit_latches_onto_state() -> None:
    """The record survives the restart that follows it."""
    module = _reducer_module()
    state = ImageState(id='app', label='App', instructions=None)

    result = module.image_reducer(
        state,
        module.DockerImageReportExitAction(
            image='app',
            restart_count=4,
            exit_code=137,
            exit_at=NOW,
            error='Killed for exceeding available memory',
        ),
    )

    assert result.restart_count == 4
    assert result.last_exit_code == 137
    assert result.last_error == 'Killed for exceeding available memory'
    # The lifecycle status is deliberately untouched — health is orthogonal.
    assert result.status == state.status


@pytest.mark.parametrize(
    'status',
    [
        DockerItemStatus.CREATED,
        DockerItemStatus.AVAILABLE,
        DockerItemStatus.NOT_AVAILABLE,
    ],
)
def test_an_app_that_is_not_meant_to_be_up_is_never_unhealthy(
    status: DockerItemStatus,
) -> None:
    """A stopped app is off, not sick.

    `docker stop` does not reset `RestartCount` — only `docker start` does — so
    a crash-looping container that the user then stopped would keep reporting
    its restarts forever, re-latched by the very next reconcile.
    """
    stopped = _image(
        status=status,
        restart_count=CRASH_LOOP_THRESHOLD * 3,
        last_exit_code=1,
        last_exit_at=NOW - 1,
        failing_services=('openclaw-cli',),
    )

    assert derive_health(stopped, now=NOW) is DockerItemHealth.OK


def test_failing_services_read_as_crash_looping() -> None:
    """A stack reports by name, since `compose ps` has no restart counter."""
    stack = _image(failing_services=('openclaw-cli',))

    assert derive_health(stack, now=NOW) is DockerItemHealth.CRASH_LOOPING


@pytest.mark.parametrize(
    'action_name',
    ['DockerImageStopAction', 'DockerImageReleaseAction', 'DockerImageRemoveAction'],
)
def test_winding_an_app_down_clears_its_failure_record(action_name: str) -> None:
    """Stopping, releasing or deleting an app must not leave its errors behind.

    Releasing a composition removes its containers and deleting it removes the
    directory, so nothing downstream will ever contradict a stale record — the
    heading would keep naming a failed service of an app that no longer exists.
    """
    module = _reducer_module()
    broken = ImageState(
        id='openclaw',
        label='OpenClaw',
        instructions=None,
        restart_count=7,
        last_exit_code=1,
        last_exit_at=NOW,
        last_error='boom',
        failing_services=('openclaw-cli',),
    )

    result = module.image_reducer(
        broken,
        getattr(module, action_name)(image='openclaw'),
    )

    assert result.state.failing_services == ()
    assert result.state.restart_count == 0
    assert result.state.last_error == ''
    assert derive_health(result.state, now=NOW) is DockerItemHealth.OK


def test_starting_by_hand_clears_the_crash_record() -> None:
    """A manual start is the user acknowledging whatever happened last."""
    module = _reducer_module()
    crashed = ImageState(
        id='portainer',
        label='Portainer',
        instructions=None,
        restart_count=9,
        last_exit_code=1,
        last_exit_at=NOW,
        last_error='boom',
    )

    result = module.image_reducer(
        crashed,
        module.DockerImageRunAction(image='portainer'),
    )

    assert result.state.restart_count == 0
    assert result.state.last_exit_code is None
    assert result.state.last_error == ''
    assert derive_health(result.state, now=NOW) is DockerItemHealth.OK
