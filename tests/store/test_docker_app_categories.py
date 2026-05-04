"""Tests for Docker app category metadata."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast

DOCKER_SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app' / 'services' / '080-docker'


class DockerEntry(Protocol):
    """Protocol for Docker entry fields used by these tests."""

    category: str | None


class AppsModule(Protocol):
    """Protocol for Docker app registry members used by these tests."""

    IMAGES: dict[str, DockerEntry]


def _import_apps() -> AppsModule:
    """Import the Docker apps registry as the Docker service would."""
    docker_path = str(DOCKER_SERVICE_PATH)
    if docker_path not in sys.path:
        sys.path.insert(0, docker_path)

    try:
        return cast('AppsModule', import_module('apps'))
    finally:
        if docker_path in sys.path:
            sys.path.remove(docker_path)


def test_builtin_docker_apps_have_expected_categories() -> None:
    """Important built-in apps are assigned to discovery categories."""
    apps = _import_apps()

    expected_categories = {
        'home_assistant': 'Home Automation',
        'home_bridge': 'Home Automation',
        'pi_hole': 'Networking',
        'envoy_grpc': 'Networking',
        'hermes': 'AI Agents',
        'openclaw': 'AI Agents',
        'ollama': 'AI Engines',
        'open_webui': 'AI Engines',
        'twingate': 'Remote Access',
        'pangolin': 'Remote Access',
        'ngrok': 'Remote Access',
        'immich': 'Files',
        'portainer': 'Container Management',
    }

    for image_id, category in expected_categories.items():
        assert apps.IMAGES[image_id].category == category
