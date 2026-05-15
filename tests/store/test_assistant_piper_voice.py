"""Tests for the Piper voice selection actions on the assistant reducer."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from ubo_app.engines.piper_catalog import DEFAULT_PIPER_VOICE_ID
from ubo_app.store.services.assistant import (
    AssistantDownloadPiperVoiceAction,
    AssistantDownloadPiperVoiceEvent,
    AssistantSetPiperDownloadedVoicesAction,
    AssistantSetSelectedPiperVoiceAction,
    _load_piper_voice,
)

if TYPE_CHECKING:
    from types import ModuleType

    import pytest
    from redux import BaseAction

    from ubo_app.store.services.assistant import AssistantState

SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/090-assistant'


def _state_path() -> Path:
    """Return the live ``PERSISTENT_STORE_PATH`` (post conftest monkey-patch).

    See ``test_localization._state_path`` for why this is lazy.
    """
    import ubo_app.constants

    return ubo_app.constants.PERSISTENT_STORE_PATH


class AssistantReducer(Protocol):
    """Protocol for the assistant reducer."""

    __globals__: dict[str, type[BaseAction]]

    def __call__(
        self,
        state: AssistantState | None,
        action: BaseAction,
    ) -> AssistantState:
        """Reduce an assistant state with one action."""
        ...


def _load_assistant_reducer(monkeypatch: pytest.MonkeyPatch) -> AssistantReducer:
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())
    spec = importlib.util.spec_from_file_location(
        'assistant_service_reducer_piper',
        SERVICE_PATH / 'reducer.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast('AssistantReducer', module.reducer)


def _assistant_types() -> ModuleType:
    return sys.modules['ubo_app.store.services.assistant']


def _init_action(reducer: AssistantReducer) -> BaseAction:
    init_action_type = cast('type[BaseAction]', reducer.__globals__['InitAction'])
    return init_action_type()


def test_initial_piper_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Initial state has a non-empty Piper voice and an empty downloaded set.

    The exact ``selected_piper_voice`` is seeded from the on-disk persisted
    value at module-import time, so this asserts only the invariants that
    hold regardless of environment; the default-resolution itself is
    covered by ``test_persisted_*`` below.
    """
    reducer = _load_assistant_reducer(monkeypatch)
    state = cast('AssistantState', reducer(None, _init_action(reducer)))
    assert state.selected_piper_voice
    assert state.piper_downloaded_voices == ()


def test_set_selected_piper_voice_updates_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selecting a voice updates ``selected_piper_voice`` on state.

    No event is emitted — the subprocess tracks the value via a gRPC
    autorun and reconciles the loaded model in ``run_tts``.
    """
    reducer = _load_assistant_reducer(monkeypatch)
    state = cast('AssistantState', reducer(None, _init_action(reducer)))
    target_voice = 'es/es_ES/davefx/medium/es_ES-davefx-medium'

    new_state = cast(
        'AssistantState',
        reducer(state, AssistantSetSelectedPiperVoiceAction(voice_id=target_voice)),
    )
    assert new_state.selected_piper_voice == target_voice


def test_download_piper_voice_emits_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dispatching a download action emits a download event for the engine."""
    from redux import CompleteReducerResult

    reducer = _load_assistant_reducer(monkeypatch)
    state = cast('AssistantState', reducer(None, _init_action(reducer)))
    target_voice = 'de/de_DE/thorsten/medium/de_DE-thorsten-medium'

    result = reducer(
        state,
        AssistantDownloadPiperVoiceAction(voice_id=target_voice),
    )
    assert isinstance(result, CompleteReducerResult)
    assert result.events is not None
    assert any(
        isinstance(e, AssistantDownloadPiperVoiceEvent) and e.voice_id == target_voice
        for e in result.events
    )


def test_set_piper_downloaded_voices_updates_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refreshing the cached downloaded set replaces it on state."""
    reducer = _load_assistant_reducer(monkeypatch)
    state = cast('AssistantState', reducer(None, _init_action(reducer)))
    voices = (
        DEFAULT_PIPER_VOICE_ID,
        'fr/fr_FR/siwis/medium/fr_FR-siwis-medium',
    )

    new_state = cast(
        'AssistantState',
        reducer(state, AssistantSetPiperDownloadedVoicesAction(voices=voices)),
    )
    assert new_state.piper_downloaded_voices == voices


def test_persisted_piper_voice_round_trips_through_file() -> None:
    """A Piper voice written to ``state.json`` is read back on next boot.

    Calls ``read_from_persistent_store`` directly because in production the
    function runs once at module-import time as the default for the
    ``AssistantState.selected_piper_voice`` field — same path the app
    takes on every restart, but not reachable via ``AssistantState()``
    after the module is already cached in ``sys.modules``.
    """
    from ubo_app.utils.persistent_store import read_from_persistent_store

    target_voice = 'es/es_ES/davefx/medium/es_ES-davefx-medium'
    _state_path().parent.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(
        json.dumps({'assistant:selected_piper_voice': target_voice}),
    )

    loaded = read_from_persistent_store(
        'assistant:selected_piper_voice',
        default=DEFAULT_PIPER_VOICE_ID,
        mapper=_load_piper_voice,
    )
    assert loaded == target_voice


def test_persisted_empty_piper_voice_falls_back_to_default() -> None:
    """Corrupted / empty persisted value never bricks the device."""
    from ubo_app.utils.persistent_store import read_from_persistent_store

    _state_path().parent.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(
        json.dumps({'assistant:selected_piper_voice': ''}),
    )

    loaded = read_from_persistent_store(
        'assistant:selected_piper_voice',
        default=DEFAULT_PIPER_VOICE_ID,
        mapper=_load_piper_voice,
    )
    assert loaded == DEFAULT_PIPER_VOICE_ID


def test_persisted_missing_piper_key_uses_default() -> None:
    """When ``state.json`` exists but has no piper voice key, default applies."""
    from ubo_app.utils.persistent_store import read_from_persistent_store

    _state_path().parent.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(json.dumps({'something_else': True}))

    loaded = read_from_persistent_store(
        'assistant:selected_piper_voice',
        default=DEFAULT_PIPER_VOICE_ID,
        mapper=_load_piper_voice,
    )
    assert loaded == DEFAULT_PIPER_VOICE_ID
