"""Tests for the named generic LLM provider add flow."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ubo_app.engines import generic_llm
from ubo_app.store.input.types import InputMethod, InputResult
from ubo_app.store.services.assistant import (
    AssistantAddGenericLLMProviderAction,
    AssistantSelectGenericLLMProviderAction,
    AssistantSetSelectedLLMAction,
)
from ubo_app.store.services.notifications import NotificationsAddAction
from ubo_app.utils import secrets
from ubo_app.utils.text import slugify

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from redux import BaseAction


class _FakeStore:
    def __init__(self) -> None:
        self.dispatched: list[BaseAction] = []

    def dispatch(self, *actions: BaseAction) -> None:
        self.dispatched.extend(actions)


@pytest.mark.parametrize(
    ('name', 'expected'),
    [
        ('My Server', 'my_server'),
        ('  Hermes!  ', 'hermes'),
        ('LLM @ Home #2', 'llm_home_2'),
        ('***', ''),
    ],
)
def test_slugify_provider_name(name: str, expected: str) -> None:
    """Display names reduce to dotenv-safe slugs."""
    assert slugify(name) == expected


def _patch_flow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    form_data: Mapping[str, str],
    existing_provider_ids: set[str],
) -> _FakeStore:
    fake_secrets_path = tmp_path / '.secrets.env'
    fake_secrets_path.write_text('')
    monkeypatch.setattr(secrets, 'SECRETS_PATH', fake_secrets_path)

    fake_store = _FakeStore()
    monkeypatch.setattr(generic_llm, 'store', fake_store)

    async def fake_ubo_input(
        *_args: object,
        **_kwargs: object,
    ) -> tuple[str, InputResult]:
        return '', InputResult(
            data=dict(form_data),
            files={},
            method=InputMethod.WEB_DASHBOARD,
        )

    monkeypatch.setattr(generic_llm, 'ubo_input', fake_ubo_input)

    async def fake_list_models(
        self: generic_llm.GenericLLMEngine,  # noqa: ARG001
        **_kwargs: object,
    ) -> Sequence[str]:
        return ('hermes-agent', 'other-model')

    monkeypatch.setattr(
        generic_llm.GenericLLMEngine,
        '_list_models',
        fake_list_models,
    )
    monkeypatch.setattr(
        generic_llm.GenericLLMEngine,
        '_existing_provider_ids',
        lambda _self: existing_provider_ids,
    )

    return fake_store


async def test_add_provider_flow_registers_and_activates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The add flow writes per-provider secrets and activates the provider."""
    fake_store = _patch_flow(
        monkeypatch,
        tmp_path,
        form_data={
            'name': 'My Server',
            'base_url': 'http://10.0.0.2:8080/v1/',
            'api_key': 'key-123',
            'model': 'hermes-agent',
        },
        existing_provider_ids=set(),
    )

    await generic_llm.GenericLLMEngine()._setup()  # noqa: SLF001

    base_url_key, api_key_key, model_key = generic_llm.provider_secret_ids(
        'my_server',
    )
    assert secrets.read_secret(base_url_key) == 'http://10.0.0.2:8080/v1'
    assert secrets.read_secret(api_key_key) == 'key-123'
    assert secrets.read_secret(model_key) == 'hermes-agent'

    add_actions = [
        action
        for action in fake_store.dispatched
        if isinstance(action, AssistantAddGenericLLMProviderAction)
    ]
    assert len(add_actions) == 1
    assert add_actions[0].provider_id == 'my_server'
    assert add_actions[0].label == 'My Server'

    # activate_provider copied the credentials into the canonical keys and
    # selected the provider.
    assert (
        secrets.read_secret(generic_llm.GENERIC_LLM_BASE_URL_SECRET_ID)
        == 'http://10.0.0.2:8080/v1'
    )
    assert any(
        isinstance(action, AssistantSelectGenericLLMProviderAction)
        and action.provider_id == 'my_server'
        for action in fake_store.dispatched
    )
    assert any(
        isinstance(action, AssistantSetSelectedLLMAction)
        for action in fake_store.dispatched
    )


async def test_add_provider_flow_rejects_duplicate_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A provider id collision aborts the add flow with a notification."""
    fake_store = _patch_flow(
        monkeypatch,
        tmp_path,
        form_data={
            'name': 'My Server',
            'base_url': 'http://10.0.0.2:8080/v1',
        },
        existing_provider_ids={'my_server'},
    )

    await generic_llm.GenericLLMEngine()._setup()  # noqa: SLF001

    assert not any(
        isinstance(action, AssistantAddGenericLLMProviderAction)
        for action in fake_store.dispatched
    )
    assert any(
        isinstance(action, NotificationsAddAction)
        for action in fake_store.dispatched
    )
    base_url_key, _, _ = generic_llm.provider_secret_ids('my_server')
    assert secrets.read_secret(base_url_key) is None
