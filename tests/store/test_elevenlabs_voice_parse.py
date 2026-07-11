"""Tests for parsing the ElevenLabs ``GET /v2/voices`` payload."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

import aiohttp
import pytest

from ubo_app.engines import elevenlabs
from ubo_app.engines.elevenlabs import ElevenLabsEngine, _parse_voices_page
from ubo_app.store.input.types import InputMethod, InputResult
from ubo_app.store.services.assistant import (
    AssistantAddElevenLabsVoiceAction,
    AssistantSetElevenLabsAvailableVoicesAction,
    ElevenLabsVoiceEntry,
)
from ubo_app.store.services.notifications import NotificationsAddAction
from ubo_app.utils import secrets

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from redux import BaseAction


class _RecordingStore:
    def __init__(self) -> None:
        self.dispatched: list[BaseAction] = []

    def dispatch(self, *actions: BaseAction) -> None:
        self.dispatched.extend(actions)


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None: ...

    async def json(self) -> object:
        return self._payload

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _FakeSession:
    def __init__(self, pages: Sequence[object]) -> None:
        self._pages = pages
        self.requested_params: list[dict[str, str]] = []

    def get(self, _url: str, *, params: dict[str, str]) -> _FakeResponse:
        self.requested_params.append(params)
        return _FakeResponse(self._pages[len(self.requested_params) - 1])

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


def _response_error(status: int) -> aiohttp.ClientResponseError:
    return aiohttp.ClientResponseError(
        request_info=aiohttp.RequestInfo(
            url='https://api.elevenlabs.io/v2/voices',  # type: ignore[arg-type]
            method='GET',
            headers=aiohttp.typedefs.CIMultiDict(),  # type: ignore[arg-type]
            real_url='https://api.elevenlabs.io/v2/voices',  # type: ignore[arg-type]
        ),
        history=(),
        status=status,
    )


def _patch_store_and_key(
    monkeypatch: pytest.MonkeyPatch,
    *,
    api_key: str | None,
) -> _RecordingStore:
    """Redirect the engine's store and stored API key for a fetch test."""
    store = _RecordingStore()
    monkeypatch.setattr(elevenlabs, 'store', store)
    monkeypatch.setattr(elevenlabs.secrets, 'read_secret', lambda _id: api_key)
    return store


def test_parse_extracts_id_and_name() -> None:
    """Well-formed voice objects become ``ElevenLabsVoiceEntry`` items."""
    payload = {
        'voices': [
            {'voice_id': 'v1', 'name': 'Rachel', 'category': 'premade'},
            {'voice_id': 'v2', 'name': 'Adam', 'category': 'cloned'},
        ],
        'has_more': False,
    }
    entries = _parse_voices_page(payload)
    assert [(entry.id, entry.label) for entry in entries] == [
        ('v1', 'Rachel'),
        ('v2', 'Adam'),
    ]


def test_parse_skips_malformed_entries() -> None:
    """Missing/empty ids and non-dict entries are dropped, not crashing."""
    payload = {
        'voices': [
            {'voice_id': '', 'name': 'NoId'},
            {'name': 'MissingId'},
            'not-a-dict',
            {'voice_id': 'v3', 'name': 'Bella'},
        ],
    }
    entries = _parse_voices_page(payload)
    assert [entry.id for entry in entries] == ['v3']


def test_parse_non_dict_payload_is_empty() -> None:
    """A non-dict payload (error body) yields no entries instead of raising."""
    assert _parse_voices_page(None) == []
    assert _parse_voices_page([]) == []


async def test_fetch_voices_without_key_does_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No stored key means no request and no dispatch."""
    store = _patch_store_and_key(monkeypatch, api_key='')

    await ElevenLabsEngine().fetch_voices()

    assert store.dispatched == []


async def test_fetch_voices_caches_parsed_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful fetch caches the returned voices in the store."""
    store = _patch_store_and_key(monkeypatch, api_key='k' * 32)
    voices = [ElevenLabsVoiceEntry(id='v1', label='Rachel')]

    async def fake_request(
        _self: ElevenLabsEngine,
        _key: str,
    ) -> list[ElevenLabsVoiceEntry]:
        return voices

    monkeypatch.setattr(ElevenLabsEngine, '_request_voices', fake_request)

    await ElevenLabsEngine().fetch_voices()

    set_actions = [
        action
        for action in store.dispatched
        if isinstance(action, AssistantSetElevenLabsAvailableVoicesAction)
    ]
    assert len(set_actions) == 1
    assert set_actions[0].voices == tuple(voices)


@pytest.mark.parametrize(
    ('status', 'expected_fragment'),
    [
        (401, 'voices_read'),
        (403, 'voices_read'),
        (500, 'HTTP 500'),
    ],
)
async def test_fetch_voices_notifies_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    expected_fragment: str,
) -> None:
    """HTTP failures surface a flash notification and cache nothing."""
    store = _patch_store_and_key(monkeypatch, api_key='k' * 32)

    async def fake_request(
        _self: ElevenLabsEngine,
        _key: str,
    ) -> list[ElevenLabsVoiceEntry]:
        raise _response_error(status)

    monkeypatch.setattr(ElevenLabsEngine, '_request_voices', fake_request)

    await ElevenLabsEngine().fetch_voices()

    assert not any(
        isinstance(action, AssistantSetElevenLabsAvailableVoicesAction)
        for action in store.dispatched
    )
    notifications = [
        action
        for action in store.dispatched
        if isinstance(action, NotificationsAddAction)
    ]
    assert len(notifications) == 1
    assert expected_fragment in notifications[0].notification.content


async def test_fetch_voices_notifies_on_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connection errors surface a distinct 'could not reach' notification."""
    store = _patch_store_and_key(monkeypatch, api_key='k' * 32)

    async def fake_request(
        _self: ElevenLabsEngine,
        _key: str,
    ) -> list[ElevenLabsVoiceEntry]:
        raise TimeoutError

    monkeypatch.setattr(ElevenLabsEngine, '_request_voices', fake_request)

    await ElevenLabsEngine().fetch_voices()

    notifications = [
        action
        for action in store.dispatched
        if isinstance(action, NotificationsAddAction)
    ]
    assert len(notifications) == 1
    assert 'Could not reach' in notifications[0].notification.content


async def test_request_voices_follows_next_page_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Paging follows next_page_token until has_more is false."""
    pages = [
        {
            'voices': [{'voice_id': 'v1', 'name': 'Rachel'}],
            'has_more': True,
            'next_page_token': 'tok-2',
        },
        {
            'voices': [{'voice_id': 'v2', 'name': 'Adam'}],
            'has_more': False,
        },
    ]
    session = _FakeSession(pages)
    monkeypatch.setattr(
        elevenlabs.aiohttp,
        'ClientSession',
        lambda **_kwargs: session,
    )

    entries = await ElevenLabsEngine()._request_voices('k' * 32)  # noqa: SLF001

    assert [entry.id for entry in entries] == ['v1', 'v2']
    # First request carries no token; the second carries the token from page 1.
    assert 'next_page_token' not in session.requested_params[0]
    assert session.requested_params[1]['next_page_token'] == 'tok-2'  # noqa: S105


async def test_request_voices_stops_when_token_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``has_more`` without a token stops paging instead of looping forever."""
    pages = [{'voices': [{'voice_id': 'v1', 'name': 'Rachel'}], 'has_more': True}]
    session = _FakeSession(pages)
    monkeypatch.setattr(
        elevenlabs.aiohttp,
        'ClientSession',
        lambda **_kwargs: session,
    )

    entries = await ElevenLabsEngine()._request_voices('k' * 32)  # noqa: SLF001

    assert [entry.id for entry in entries] == ['v1']
    assert len(session.requested_params) == 1


async def test_setup_registers_named_primary_voice(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A name entered during setup registers the primary voice in the picker."""
    secrets_path = tmp_path / '.secrets.env'
    secrets_path.write_text('')
    monkeypatch.setattr(secrets, 'SECRETS_PATH', secrets_path)
    store = _RecordingStore()
    monkeypatch.setattr(elevenlabs, 'store', store)

    async def fake_ubo_input(*_args: object, **_kwargs: object) -> object:
        return '', InputResult(
            data={'api_key': 'k' * 32, 'voice_id': 'v' * 20, 'name': 'Deep Voice'},
            files={},
            method=InputMethod.WEB_DASHBOARD,
        )

    monkeypatch.setattr(elevenlabs, 'ubo_input', fake_ubo_input)

    await ElevenLabsEngine()._setup()  # noqa: SLF001

    add_actions = [
        action
        for action in store.dispatched
        if isinstance(action, AssistantAddElevenLabsVoiceAction)
    ]
    assert len(add_actions) == 1
    assert add_actions[0].name == 'Deep Voice'
    assert secrets.read_secret('elevenlabs_api_key') == 'k' * 32
