"""Tests for parsing the Mistral ``GET /v1/audio/voices`` payload."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

import aiohttp
import pytest

from ubo_app.engines import mistral
from ubo_app.engines.mistral import MistralEngine, _parse_voices_page
from ubo_app.store.services.assistant import (
    AssistantSetMistralAvailableVoicesAction,
    MistralVoiceEntry,
)
from ubo_app.store.services.notifications import NotificationsAddAction

if TYPE_CHECKING:
    from collections.abc import Sequence

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
        self.requested_offsets: list[str] = []

    def get(self, _url: str, *, params: dict[str, str]) -> _FakeResponse:
        self.requested_offsets.append(params['offset'])
        return _FakeResponse(self._pages[len(self.requested_offsets) - 1])

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


def _response_error(status: int) -> aiohttp.ClientResponseError:
    return aiohttp.ClientResponseError(
        request_info=aiohttp.RequestInfo(
            url='https://api.mistral.ai/v1/audio/voices',  # type: ignore[arg-type]
            method='GET',
            headers=aiohttp.typedefs.CIMultiDict(),  # type: ignore[arg-type]
            real_url='https://api.mistral.ai/v1/audio/voices',  # type: ignore[arg-type]
        ),
        history=(),
        status=status,
    )


def test_parse_prefers_slug_over_uuid() -> None:
    """Voices expose a human ``slug``, which is used as the id when present."""
    payload = {
        'items': [
            {'id': 'uuid-1', 'slug': 'casual_male', 'name': 'Casual Male'},
            {'id': 'uuid-2', 'slug': 'fr_marie_neutral', 'name': 'Marie'},
        ],
        'total': 2,
    }
    entries = _parse_voices_page(payload)
    assert [(entry.id, entry.label) for entry in entries] == [
        ('casual_male', 'Casual Male'),
        ('fr_marie_neutral', 'Marie'),
    ]


def test_parse_falls_back_to_uuid_when_no_slug() -> None:
    """Cloned voices may have only a UUID id (no slug)."""
    payload = {
        'items': [
            {'id': 'uuid-3', 'name': 'My Clone'},
            {'id': 'uuid-4', 'slug': None, 'name': 'Other Clone'},
        ],
    }
    entries = _parse_voices_page(payload)
    assert [(entry.id, entry.label) for entry in entries] == [
        ('uuid-3', 'My Clone'),
        ('uuid-4', 'Other Clone'),
    ]


def test_parse_label_falls_back_to_id() -> None:
    """An unnamed voice labels itself with its id."""
    entries = _parse_voices_page({'items': [{'slug': 'casual_male'}]})
    assert [(entry.id, entry.label) for entry in entries] == [
        ('casual_male', 'casual_male'),
    ]


def test_parse_skips_malformed_entries() -> None:
    """Entries without any id and non-dict entries are dropped, not crashing."""
    payload = {
        'items': [
            {'name': 'NoId'},
            'not-a-dict',
            {'id': 'uuid-5', 'slug': 'pluto', 'name': 'Pluto'},
        ],
    }
    entries = _parse_voices_page(payload)
    assert [entry.id for entry in entries] == ['pluto']


def test_parse_non_dict_payload_is_empty() -> None:
    """A non-dict payload (error body) yields no entries instead of raising."""
    assert _parse_voices_page(None) == []
    assert _parse_voices_page([]) == []


def _patch_store_and_key(
    monkeypatch: pytest.MonkeyPatch,
    *,
    api_key: str | None,
) -> _RecordingStore:
    """Redirect the engine's store and stored API key for a fetch test."""
    store = _RecordingStore()
    monkeypatch.setattr(mistral, 'store', store)
    monkeypatch.setattr(mistral.secrets, 'read_secret', lambda _id: api_key)
    return store


async def test_fetch_voices_without_key_does_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No stored key means no request and no dispatch."""
    store = _patch_store_and_key(monkeypatch, api_key='')

    await MistralEngine().fetch_voices()

    assert store.dispatched == []


async def test_fetch_voices_caches_parsed_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful fetch caches the returned voices in the store."""
    store = _patch_store_and_key(monkeypatch, api_key='k' * 32)
    voices = [MistralVoiceEntry(id='casual_male', label='Casual Male')]

    async def fake_request(_self: MistralEngine, _key: str) -> list[MistralVoiceEntry]:
        return voices

    monkeypatch.setattr(MistralEngine, '_request_voices', fake_request)

    await MistralEngine().fetch_voices()

    set_actions = [
        action
        for action in store.dispatched
        if isinstance(action, AssistantSetMistralAvailableVoicesAction)
    ]
    assert len(set_actions) == 1
    assert set_actions[0].voices == tuple(voices)


@pytest.mark.parametrize(
    ('status', 'expected_fragment'),
    [
        (401, 'cannot list voices'),
        (403, 'cannot list voices'),
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

    async def fake_request(_self: MistralEngine, _key: str) -> list[MistralVoiceEntry]:
        raise _response_error(status)

    monkeypatch.setattr(MistralEngine, '_request_voices', fake_request)

    await MistralEngine().fetch_voices()

    assert not any(
        isinstance(action, AssistantSetMistralAvailableVoicesAction)
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

    async def fake_request(_self: MistralEngine, _key: str) -> list[MistralVoiceEntry]:
        raise TimeoutError

    monkeypatch.setattr(MistralEngine, '_request_voices', fake_request)

    await MistralEngine().fetch_voices()

    notifications = [
        action
        for action in store.dispatched
        if isinstance(action, NotificationsAddAction)
    ]
    assert len(notifications) == 1
    assert 'Could not reach' in notifications[0].notification.content


async def test_request_voices_pages_until_total_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Paging accumulates entries across pages and stops once total is met."""
    pages = [
        {'items': [{'slug': 'a', 'name': 'A'}], 'total': 150},
        {'items': [{'slug': 'b', 'name': 'B'}], 'total': 150},
    ]
    session = _FakeSession(pages)
    monkeypatch.setattr(mistral.aiohttp, 'ClientSession', lambda **_kwargs: session)

    entries = await MistralEngine()._request_voices('k' * 32)  # noqa: SLF001

    assert [entry.id for entry in entries] == ['a', 'b']
    # Two pages fetched at increasing offsets; stops before a third request.
    assert session.requested_offsets == ['0', '100']
