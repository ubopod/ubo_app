"""Tests for the Piper voice selection actions on the assistant reducer.

Class-identity discipline: integration tests earlier in the suite wipe
``sys.modules`` (see ``tests/fixtures/app.py``). The loader explicitly
``importlib.reload``s ``ubo_app.store.services.assistant`` before
``exec_module``'ing the reducer, and tests pull every action / event /
state class from the returned namespace — never from top-level imports.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import pytest
    from redux import BaseAction

    # Static-only — see ``_load_assistant`` for why we don't bind the
    # state class at module top level at runtime.
    from ubo_app.store.services.assistant import AssistantState


SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/090-assistant'


def _state_path() -> Path:
    """Return the live ``PERSISTENT_STORE_PATH`` (post conftest monkey-patch).

    Lazy import so the read happens after the conftest fixture has redirected
    the constant to ``tmp_path``.
    """
    import ubo_app.constants

    return ubo_app.constants.PERSISTENT_STORE_PATH


def _load_assistant(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Load the assistant reducer + namespace of Piper-related symbols."""
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())

    from ubo_app.engines import piper_catalog
    from ubo_app.store.services import assistant as assistant_module

    piper_catalog = importlib.reload(piper_catalog)
    assistant_module = importlib.reload(assistant_module)

    spec = importlib.util.spec_from_file_location(
        'assistant_service_reducer_piper',
        SERVICE_PATH / 'reducer.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    return SimpleNamespace(
        reducer=module.reducer,
        AssistantDownloadPiperVoiceAction=(
            assistant_module.AssistantDownloadPiperVoiceAction
        ),
        AssistantDownloadPiperVoiceEvent=(
            assistant_module.AssistantDownloadPiperVoiceEvent
        ),
        AssistantSetPiperDownloadedVoicesAction=(
            assistant_module.AssistantSetPiperDownloadedVoicesAction
        ),
        AssistantSetSelectedPiperVoiceAction=(
            assistant_module.AssistantSetSelectedPiperVoiceAction
        ),
        load_piper_voice=assistant_module._load_piper_voice,  # noqa: SLF001
        DEFAULT_PIPER_VOICE_ID=piper_catalog.DEFAULT_PIPER_VOICE_ID,
    )


def _init_action(ns: SimpleNamespace) -> BaseAction:
    init_action_type = cast(
        'type[BaseAction]',
        ns.reducer.__globals__['InitAction'],
    )
    return init_action_type()


def test_initial_piper_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Initial state has a non-empty Piper voice and an empty downloaded set."""
    ns = _load_assistant(monkeypatch)
    state = cast('AssistantState', ns.reducer(None, _init_action(ns)))
    assert state.selected_piper_voice
    assert state.piper_downloaded_voices == ()


def test_set_selected_piper_voice_updates_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selecting a voice updates ``selected_piper_voice`` on state.

    No event is emitted — the subprocess tracks the value via a gRPC
    autorun and reconciles the loaded model in ``run_tts``.
    """
    ns = _load_assistant(monkeypatch)
    state = cast('AssistantState', ns.reducer(None, _init_action(ns)))
    target_voice = 'es/es_ES/davefx/medium/es_ES-davefx-medium'

    new_state = cast(
        'AssistantState',
        ns.reducer(
            state,
            ns.AssistantSetSelectedPiperVoiceAction(voice_id=target_voice),
        ),
    )
    assert new_state.selected_piper_voice == target_voice


def test_download_piper_voice_emits_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dispatching a download action emits a download event for the engine."""
    from redux import CompleteReducerResult

    ns = _load_assistant(monkeypatch)
    state = cast('AssistantState', ns.reducer(None, _init_action(ns)))
    target_voice = 'de/de_DE/thorsten/medium/de_DE-thorsten-medium'

    result = ns.reducer(
        state,
        ns.AssistantDownloadPiperVoiceAction(voice_id=target_voice),
    )
    assert isinstance(result, CompleteReducerResult)
    assert result.events is not None
    assert any(
        isinstance(e, ns.AssistantDownloadPiperVoiceEvent)
        and e.voice_id == target_voice
        for e in result.events
    )


def test_set_piper_downloaded_voices_updates_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refreshing the cached downloaded set replaces it on state."""
    ns = _load_assistant(monkeypatch)
    state = cast('AssistantState', ns.reducer(None, _init_action(ns)))
    voices = (
        ns.DEFAULT_PIPER_VOICE_ID,
        'fr/fr_FR/siwis/medium/fr_FR-siwis-medium',
    )

    new_state = cast(
        'AssistantState',
        ns.reducer(
            state,
            ns.AssistantSetPiperDownloadedVoicesAction(voices=voices),
        ),
    )
    assert new_state.piper_downloaded_voices == voices


def test_persisted_piper_voice_round_trips_through_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Piper voice written to ``state.json`` is read back on next boot."""
    from ubo_app.utils.persistent_store import read_from_persistent_store

    ns = _load_assistant(monkeypatch)
    target_voice = 'es/es_ES/davefx/medium/es_ES-davefx-medium'
    _state_path().parent.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(
        json.dumps({'assistant:selected_piper_voice': target_voice}),
    )

    loaded = read_from_persistent_store(
        'assistant:selected_piper_voice',
        default=ns.DEFAULT_PIPER_VOICE_ID,
        mapper=ns.load_piper_voice,
    )
    assert loaded == target_voice


def test_persisted_empty_piper_voice_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Corrupted / empty persisted value never bricks the device."""
    from ubo_app.utils.persistent_store import read_from_persistent_store

    ns = _load_assistant(monkeypatch)
    _state_path().parent.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(
        json.dumps({'assistant:selected_piper_voice': ''}),
    )

    loaded = read_from_persistent_store(
        'assistant:selected_piper_voice',
        default=ns.DEFAULT_PIPER_VOICE_ID,
        mapper=ns.load_piper_voice,
    )
    assert loaded == ns.DEFAULT_PIPER_VOICE_ID


def test_persisted_missing_piper_key_uses_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``state.json`` exists but has no piper voice key, default applies."""
    from ubo_app.utils.persistent_store import read_from_persistent_store

    ns = _load_assistant(monkeypatch)
    _state_path().parent.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(json.dumps({'something_else': True}))

    loaded = read_from_persistent_store(
        'assistant:selected_piper_voice',
        default=ns.DEFAULT_PIPER_VOICE_ID,
        mapper=ns.load_piper_voice,
    )
    assert loaded == ns.DEFAULT_PIPER_VOICE_ID
