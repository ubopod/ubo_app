"""Tests for the Hermes Docker composition app."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from ubo_app.store.services.assistant import (
    AssistantAddGenericLLMProviderAction,
    AssistantRemoveGenericLLMProviderAction,
)
from ubo_app.utils import secrets

if TYPE_CHECKING:
    import pytest
    from redux import BaseAction


DOCKER_SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app' / 'services' / '080-docker'

# Minimal stand-in for the upstream compose file so prepare_hermes never
# touches the network in tests.
UPSTREAM_COMPOSE = """services:
  hermes-agent:
    image: ghcr.io/nesquena/hermes-agent:latest
    environment:
      - HERMES_HOME=/root/.hermes
    volumes:
      - hermes-home:/root/.hermes
      - ~/workspace:/workspace
"""


class SecretsModule(Protocol):
    """Protocol for the secrets module attributes patched by these tests."""

    SECRETS_PATH: Path


class _FakeStore:
    def __init__(self) -> None:
        self.dispatched: list[BaseAction] = []

    def dispatch(self, *actions: BaseAction) -> None:
        self.dispatched.extend(actions)


class ContainerEntryProtocol(Protocol):
    """Subset of ContainerEntry fields asserted by these tests."""

    secret_keys: tuple[str, ...]
    cleanup: object


class HermesModule(Protocol):
    """Protocol for the Hermes module members used by these tests."""

    COMPOSITIONS_PATH: Path
    HERMES_API_SERVER_KEY_SECRET: str
    HERMES_LLM_PROVIDER_SECRET_KEYS: tuple[str, str, str]
    ENTRY: ContainerEntryProtocol
    secrets: SecretsModule
    store: _FakeStore

    async def prepare_hermes(self) -> bool:
        """Prepare Hermes composition files."""
        ...

    def _cleanup_hermes(self) -> None: ...


def _import_hermes() -> HermesModule:
    """Import the Hermes module as the Docker service would."""
    docker_path = str(DOCKER_SERVICE_PATH)
    if docker_path not in sys.path:
        sys.path.insert(0, docker_path)

    try:
        return cast('HermesModule', import_module('apps.hermes'))
    finally:
        if docker_path in sys.path:
            sys.path.remove(docker_path)


def _use_temp_secrets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    hermes: HermesModule,
) -> None:
    fake_path = tmp_path / '.secrets.env'
    fake_path.write_text('')
    monkeypatch.setattr(secrets, 'SECRETS_PATH', fake_path)
    monkeypatch.setattr(hermes.secrets, 'SECRETS_PATH', fake_path)


def _prepare(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[HermesModule, _FakeStore]:
    hermes = _import_hermes()
    _use_temp_secrets(monkeypatch, tmp_path, hermes)
    monkeypatch.setattr(hermes, 'COMPOSITIONS_PATH', tmp_path)
    fake_store = _FakeStore()
    monkeypatch.setattr(hermes, 'store', fake_store)

    composition_path = tmp_path / 'hermes'
    composition_path.mkdir()
    (composition_path / 'docker-compose.yml').write_text(UPSTREAM_COMPOSE)

    return hermes, fake_store


async def test_prepare_hermes_writes_env_with_api_server_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The prepare phase enables the API server in the compose .env file."""
    hermes, _ = _prepare(monkeypatch, tmp_path)

    assert await hermes.prepare_hermes()

    env = (tmp_path / 'hermes' / '.env').read_text()
    assert 'API_SERVER_ENABLED=true' in env
    api_server_key = secrets.read_secret(hermes.HERMES_API_SERVER_KEY_SECRET)
    assert api_server_key
    assert f'HERMES_API_SERVER_KEY={api_server_key}' in env


async def test_prepare_hermes_registers_assistant_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The prepare phase auto-registers a named generic LLM provider."""
    hermes, fake_store = _prepare(monkeypatch, tmp_path)

    assert await hermes.prepare_hermes()

    base_url_key, api_key_key, model_key = hermes.HERMES_LLM_PROVIDER_SECRET_KEYS
    assert secrets.read_secret(base_url_key) == 'http://127.0.0.1:8642/v1'
    assert secrets.read_secret(api_key_key) == secrets.read_secret(
        hermes.HERMES_API_SERVER_KEY_SECRET,
    )
    assert secrets.read_secret(model_key) == 'hermes-agent'

    add_actions = [
        action
        for action in fake_store.dispatched
        if isinstance(action, AssistantAddGenericLLMProviderAction)
    ]
    assert len(add_actions) == 1
    assert add_actions[0].provider_id == 'hermes'
    assert add_actions[0].label == 'Hermes'


def test_hermes_entry_lists_all_secret_keys() -> None:
    """Uninstall clears the API server key and the LLM provider credentials."""
    hermes = _import_hermes()

    assert hermes.ENTRY.secret_keys == (
        hermes.HERMES_API_SERVER_KEY_SECRET,
        *hermes.HERMES_LLM_PROVIDER_SECRET_KEYS,
    )
    assert hermes.ENTRY.cleanup is not None


def test_cleanup_hermes_removes_assistant_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cleanup hook deregisters the assistant LLM provider."""
    hermes = _import_hermes()
    fake_store = _FakeStore()
    monkeypatch.setattr(hermes, 'store', fake_store)

    hermes._cleanup_hermes()  # noqa: SLF001

    remove_actions = [
        action
        for action in fake_store.dispatched
        if isinstance(action, AssistantRemoveGenericLLMProviderAction)
    ]
    assert len(remove_actions) == 1
    assert remove_actions[0].provider_id == 'hermes'
