"""Tests for Docker image reference matching used by the event monitor."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast

import pytest

DOCKER_SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app' / 'services' / '080-docker'


class DockerContainerModule(Protocol):
    """Protocol for the docker_container members used by these tests."""

    def _image_ref_matches(self, ref: str | None, image_path: str) -> bool: ...


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
