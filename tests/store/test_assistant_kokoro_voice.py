"""Tests for the Kokoro voice selection actions on the assistant reducer.

Class-identity discipline mirrors ``test_assistant_piper_voice.py``:
integration tests earlier in the suite wipe ``sys.modules`` (see
``tests/fixtures/app.py``). The loader explicitly ``importlib.reload``s
``ubo_app.store.services.assistant`` before ``exec_module``'ing the
reducer, and tests pull every action / event / state class from the
returned namespace — never from top-level imports.
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
    """Load the assistant reducer + namespace of Kokoro-related symbols."""
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())

    from ubo_app.engines import kokoro_catalog
    from ubo_app.store.services import assistant as assistant_module

    kokoro_catalog = importlib.reload(kokoro_catalog)
    assistant_module = importlib.reload(assistant_module)

    spec = importlib.util.spec_from_file_location(
        'assistant_service_reducer_kokoro',
        SERVICE_PATH / 'reducer.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    return SimpleNamespace(
        reducer=module.reducer,
        AssistantDownloadKokoroAction=(
            assistant_module.AssistantDownloadKokoroAction
        ),
        AssistantDownloadKokoroEvent=(
            assistant_module.AssistantDownloadKokoroEvent
        ),
        AssistantSetKokoroDownloadedAction=(
            assistant_module.AssistantSetKokoroDownloadedAction
        ),
        AssistantSetSelectedKokoroVoiceAction=(
            assistant_module.AssistantSetSelectedKokoroVoiceAction
        ),
        load_kokoro_voice=assistant_module._load_kokoro_voice,  # noqa: SLF001
        DEFAULT_KOKORO_VOICE_ID=kokoro_catalog.DEFAULT_KOKORO_VOICE_ID,
    )


def _init_action(ns: SimpleNamespace) -> BaseAction:
    init_action_type = cast(
        'type[BaseAction]',
        ns.reducer.__globals__['InitAction'],
    )
    return init_action_type()


def test_initial_kokoro_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Initial state has a non-empty Kokoro voice and ``kokoro_is_downloaded=False``."""
    ns = _load_assistant(monkeypatch)
    state = cast('AssistantState', ns.reducer(None, _init_action(ns)))
    assert state.selected_kokoro_voice
    assert state.kokoro_is_downloaded is False


def test_set_selected_kokoro_voice_updates_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selecting a voice updates ``selected_kokoro_voice`` on state.

    No event is emitted — the subprocess tracks the value via a gRPC
    autorun and ``KokoroTTSService.request_voice`` rewrites settings
    before the next utterance.
    """
    ns = _load_assistant(monkeypatch)
    state = cast('AssistantState', ns.reducer(None, _init_action(ns)))
    target_voice = 'bf_emma'

    new_state = cast(
        'AssistantState',
        ns.reducer(
            state,
            ns.AssistantSetSelectedKokoroVoiceAction(voice_id=target_voice),
        ),
    )
    assert new_state.selected_kokoro_voice == target_voice


def test_download_kokoro_emits_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dispatching a download action emits a download event for the engine."""
    from redux import CompleteReducerResult

    ns = _load_assistant(monkeypatch)
    state = cast('AssistantState', ns.reducer(None, _init_action(ns)))
    target_voice = ns.DEFAULT_KOKORO_VOICE_ID

    result = ns.reducer(
        state,
        ns.AssistantDownloadKokoroAction(voice_id=target_voice),
    )
    assert isinstance(result, CompleteReducerResult)
    assert result.events is not None
    assert any(
        isinstance(e, ns.AssistantDownloadKokoroEvent)
        and e.voice_id == target_voice
        for e in result.events
    )


def test_set_kokoro_downloaded_updates_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flipping the cached downloaded flag updates state in both directions."""
    ns = _load_assistant(monkeypatch)
    state = cast('AssistantState', ns.reducer(None, _init_action(ns)))

    on_state = cast(
        'AssistantState',
        ns.reducer(
            state,
            ns.AssistantSetKokoroDownloadedAction(downloaded=True),
        ),
    )
    assert on_state.kokoro_is_downloaded is True

    off_state = cast(
        'AssistantState',
        ns.reducer(
            on_state,
            ns.AssistantSetKokoroDownloadedAction(downloaded=False),
        ),
    )
    assert off_state.kokoro_is_downloaded is False


def test_persisted_kokoro_voice_round_trips_through_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Kokoro voice written to ``state.json`` is read back on next boot."""
    from ubo_app.utils.persistent_store import read_from_persistent_store

    ns = _load_assistant(monkeypatch)
    target_voice = 'jf_alpha'
    _state_path().parent.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(
        json.dumps({'assistant:selected_kokoro_voice': target_voice}),
    )

    loaded = read_from_persistent_store(
        'assistant:selected_kokoro_voice',
        default=ns.DEFAULT_KOKORO_VOICE_ID,
        mapper=ns.load_kokoro_voice,
    )
    assert loaded == target_voice


def test_persisted_empty_kokoro_voice_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Corrupted / empty persisted value never bricks the device."""
    from ubo_app.utils.persistent_store import read_from_persistent_store

    ns = _load_assistant(monkeypatch)
    _state_path().parent.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(
        json.dumps({'assistant:selected_kokoro_voice': ''}),
    )

    loaded = read_from_persistent_store(
        'assistant:selected_kokoro_voice',
        default=ns.DEFAULT_KOKORO_VOICE_ID,
        mapper=ns.load_kokoro_voice,
    )
    assert loaded == ns.DEFAULT_KOKORO_VOICE_ID


def test_persisted_missing_kokoro_key_uses_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``state.json`` exists but has no kokoro voice key, default applies."""
    from ubo_app.utils.persistent_store import read_from_persistent_store

    ns = _load_assistant(monkeypatch)
    _state_path().parent.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(json.dumps({'something_else': True}))

    loaded = read_from_persistent_store(
        'assistant:selected_kokoro_voice',
        default=ns.DEFAULT_KOKORO_VOICE_ID,
        mapper=ns.load_kokoro_voice,
    )
    assert loaded == ns.DEFAULT_KOKORO_VOICE_ID
