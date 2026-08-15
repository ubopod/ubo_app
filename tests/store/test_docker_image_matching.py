"""Tests for Docker image reference matching used by the event monitor."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Protocol, cast

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

DOCKER_SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app' / 'services' / '080-docker'


class DockerContainerModule(Protocol):
    """Protocol for the docker_container members used by these tests."""

    def _image_ref_matches(self, ref: str | None, image_path: str) -> bool: ...
    def _monitor_events(
        self,
        image_id: str,
        get_docker_id: Callable[[], str],
    ) -> None: ...
    IMAGES: dict[str, object]
    docker: object


def _import_docker_container() -> DockerContainerModule:
    """Import the docker_container module as the Docker service would."""
    docker_path = str(DOCKER_SERVICE_PATH)
    if docker_path not in sys.path:
        sys.path.insert(0, docker_path)

    try:
        return cast('DockerContainerModule', import_module('docker_container'))
    finally:
        if docker_path in sys.path:
            sys.path.remove(docker_path)


@pytest.mark.parametrize(
    ('ref', 'image_path', 'expected'),
    [
        ('ollama/ollama:latest', 'ollama/ollama:latest', True),
        ('docker.io/ollama/ollama:latest', 'ollama/ollama:latest', True),
        ('ghcr.io/open-webui/open-webui:main', 'open-webui/open-webui:main', True),
        ('myollama/ollama:latest', 'ollama/ollama:latest', False),
        (None, 'ollama/ollama:latest', False),
    ],
)
def test_image_ref_matches(*, ref: str | None, image_path: str, expected: bool) -> None:
    """Registry-stripped references match regardless of the registry prefix."""
    docker_container = _import_docker_container()
    assert docker_container._image_ref_matches(ref, image_path) is expected  # noqa: SLF001


class _FakeEventStream(list):
    """A list that also looks like the ``docker events()`` stream handle."""

    def close(self) -> None:
        pass


def test_monitor_events_survives_transient_image_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 404 on a partial 'pull' event must not kill the monitor thread.

    ``pull`` events fire per-layer, so ``images.get`` can 404 (ImageNotFound)
    before the image is actually committed/tagged. Re-raising here used to
    escape ``_monitor_events`` for good -- nothing restarts the thread, and
    ``_active_monitors`` is never cleared on this path, so the image's status
    froze forever. Reproduces Sentry UBO-APP-QC (223 events, 17 users).
    """
    docker_container = _import_docker_container()
    import docker.errors

    dispatched: list[object] = []
    monkeypatch.setattr(
        docker_container,
        'store',
        SimpleNamespace(
            subscribe_event=lambda *_args, **_kwargs: None,
            dispatch=dispatched.append,
        ),
    )
    monkeypatch.setitem(
        docker_container.IMAGES,
        'test-image',
        SimpleNamespace(
            full_path='docker.io/library/test-image:latest',
            path='library/test-image:latest',
        ),
    )

    class _FakeImages:
        def __init__(self) -> None:
            self.calls = 0

        def get(self, _path: str) -> object:
            self.calls += 1
            if self.calls == 1:
                msg = 'not found yet'
                raise docker.errors.ImageNotFound(msg)
            return SimpleNamespace(id=None)

    fake_images = _FakeImages()

    class _FakeDockerClient:
        images = fake_images

        def events(self, *, decode: bool, filters: dict) -> _FakeEventStream:  # noqa: ARG002
            return _FakeEventStream(
                [
                    {'Type': 'image', 'Action': 'pull', 'id': 'library'},
                    {'Type': 'image', 'Action': 'pull', 'id': 'library'},
                ],
            )

    monkeypatch.setattr(docker_container.docker, 'from_env', _FakeDockerClient)

    # Must not raise -- that's the whole point of the fix.
    docker_container._monitor_events('test-image', lambda: '')  # noqa: SLF001

    # Both pull events were processed: the first 404s and is dropped, the
    # second resolves -- proving the loop kept running instead of dying.
    assert fake_images.calls == 2
