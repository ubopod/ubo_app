"""Tests for the Moonshine STT actions on the assistant reducer.

Class-identity discipline: integration tests earlier in the suite wipe
``sys.modules`` (see ``tests/fixtures/app.py``). The loader explicitly
``importlib.reload``s ``ubo_app.store.services.assistant`` before
``exec_module``'ing the reducer, and tests pull every action / state class
from the returned namespace — never from top-level imports.
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

    from ubo_app.store.services.assistant import AssistantState


SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/090-assistant'


def _state_path() -> Path:
    """Return the live ``PERSISTENT_STORE_PATH`` (post conftest monkey-patch)."""
    import ubo_app.constants

    return ubo_app.constants.PERSISTENT_STORE_PATH


def _load_assistant(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Load the assistant reducer + namespace of Moonshine-related symbols."""
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())

    # ``import_module`` (not ``from ... import``) guarantees the module is
    # registered in ``sys.modules`` even after an earlier test wiped it — a
    # bare ``from package import submodule`` would return the stale parent
    # attribute and make the following ``reload`` raise. Reload picks up the
    # conftest ``PERSISTENT_STORE_PATH`` monkeypatch in the field defaults.
    moonshine_catalog = importlib.reload(
        importlib.import_module('ubo_app.engines.moonshine_catalog'),
    )
    assistant_module = importlib.reload(
        importlib.import_module('ubo_app.store.services.assistant'),
    )

    spec = importlib.util.spec_from_file_location(
        'assistant_service_reducer_moonshine',
        SERVICE_PATH / 'reducer.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    return SimpleNamespace(
        reducer=module.reducer,
        AssistantSetSelectedMoonshineModelAction=(
            assistant_module.AssistantSetSelectedMoonshineModelAction
        ),
        AssistantDownloadMoonshineModelAction=(
            assistant_module.AssistantDownloadMoonshineModelAction
        ),
        AssistantDownloadMoonshineModelEvent=(
            assistant_module.AssistantDownloadMoonshineModelEvent
        ),
        AssistantDeleteMoonshineModelAction=(
            assistant_module.AssistantDeleteMoonshineModelAction
        ),
        AssistantDeleteMoonshineModelEvent=(
            assistant_module.AssistantDeleteMoonshineModelEvent
        ),
        AssistantAddMoonshineDownloadedModelAction=(
            assistant_module.AssistantAddMoonshineDownloadedModelAction
        ),
        AssistantRemoveMoonshineDownloadedModelAction=(
            assistant_module.AssistantRemoveMoonshineDownloadedModelAction
        ),
        AssistantSetMoonshineDownloadingAction=(
            assistant_module.AssistantSetMoonshineDownloadingAction
        ),
        load_moonshine_model=assistant_module._load_moonshine_model,  # noqa: SLF001
        DEFAULT_MOONSHINE_MODEL_ID=moonshine_catalog.DEFAULT_MOONSHINE_MODEL_ID,
    )


def _init_action(ns: SimpleNamespace) -> BaseAction:
    init_action_type = cast(
        'type[BaseAction]',
        ns.reducer.__globals__['InitAction'],
    )
    return init_action_type()


def test_initial_moonshine_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Initial state defaults to the tiny model with an empty downloaded set."""
    ns = _load_assistant(monkeypatch)
    state = cast('AssistantState', ns.reducer(None, _init_action(ns)))
    assert state.selected_moonshine_model == 'tiny'
    assert state.moonshine_downloaded_models == ()
    assert state.moonshine_downloading_model == ''


def test_set_selected_moonshine_model_updates_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selecting a model updates ``selected_moonshine_model`` with no event."""
    ns = _load_assistant(monkeypatch)
    state = cast('AssistantState', ns.reducer(None, _init_action(ns)))

    new_state = cast(
        'AssistantState',
        ns.reducer(
            state,
            ns.AssistantSetSelectedMoonshineModelAction(model_id='small-streaming'),
        ),
    )
    assert new_state.selected_moonshine_model == 'small-streaming'


def test_download_action_emits_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """Download action emits a Download event for the subprocess to handle."""
    from redux import CompleteReducerResult

    ns = _load_assistant(monkeypatch)
    state = cast('AssistantState', ns.reducer(None, _init_action(ns)))

    result = ns.reducer(
        state,
        ns.AssistantDownloadMoonshineModelAction(model_id='base'),
    )
    assert isinstance(result, CompleteReducerResult)
    assert result.events is not None
    assert any(
        isinstance(e, ns.AssistantDownloadMoonshineModelEvent) and e.model_id == 'base'
        for e in result.events
    )


def test_delete_action_emits_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """Delete action emits a Delete event for the subprocess to handle."""
    from redux import CompleteReducerResult

    ns = _load_assistant(monkeypatch)
    state = cast('AssistantState', ns.reducer(None, _init_action(ns)))

    result = ns.reducer(
        state,
        ns.AssistantDeleteMoonshineModelAction(model_id='tiny'),
    )
    assert isinstance(result, CompleteReducerResult)
    assert result.events is not None
    assert any(
        isinstance(e, ns.AssistantDeleteMoonshineModelEvent) and e.model_id == 'tiny'
        for e in result.events
    )


def test_remove_downloaded_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Removing a downloaded model drops it from the set."""
    ns = _load_assistant(monkeypatch)
    state = cast('AssistantState', ns.reducer(None, _init_action(ns)))
    for model_id in ('tiny', 'base'):
        state = cast(
            'AssistantState',
            ns.reducer(
                state,
                ns.AssistantAddMoonshineDownloadedModelAction(model_id=model_id),
            ),
        )
    assert state.moonshine_downloaded_models == ('tiny', 'base')

    state = cast(
        'AssistantState',
        ns.reducer(
            state,
            ns.AssistantRemoveMoonshineDownloadedModelAction(model_id='tiny'),
        ),
    )
    assert state.moonshine_downloaded_models == ('base',)


def test_add_downloaded_model_is_additive_and_deduped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adding downloaded models unions them; duplicates are ignored."""
    ns = _load_assistant(monkeypatch)
    state = cast('AssistantState', ns.reducer(None, _init_action(ns)))

    state = cast(
        'AssistantState',
        ns.reducer(
            state,
            ns.AssistantAddMoonshineDownloadedModelAction(model_id='tiny'),
        ),
    )
    assert state.moonshine_downloaded_models == ('tiny',)

    state = cast(
        'AssistantState',
        ns.reducer(
            state,
            ns.AssistantAddMoonshineDownloadedModelAction(model_id='base'),
        ),
    )
    assert state.moonshine_downloaded_models == ('tiny', 'base')

    # Re-adding an existing model is a no-op (no duplicate, same object back).
    same = ns.reducer(
        state,
        ns.AssistantAddMoonshineDownloadedModelAction(model_id='tiny'),
    )
    assert same is state


def test_set_downloading_flag_toggles(monkeypatch: pytest.MonkeyPatch) -> None:
    """The downloading flag tracks the model id the subprocess reports."""
    ns = _load_assistant(monkeypatch)
    state = cast('AssistantState', ns.reducer(None, _init_action(ns)))

    state = cast(
        'AssistantState',
        ns.reducer(
            state,
            ns.AssistantSetMoonshineDownloadingAction(model_id='small-streaming'),
        ),
    )
    assert state.moonshine_downloading_model == 'small-streaming'

    state = cast(
        'AssistantState',
        ns.reducer(state, ns.AssistantSetMoonshineDownloadingAction(model_id='')),
    )
    assert state.moonshine_downloading_model == ''


def test_persisted_moonshine_model_round_trips(monkeypatch: pytest.MonkeyPatch) -> None:
    """A model written to ``state.json`` is read back on next boot."""
    from ubo_app.utils.persistent_store import read_from_persistent_store

    ns = _load_assistant(monkeypatch)
    _state_path().parent.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(
        json.dumps({'assistant:selected_moonshine_model': 'medium-streaming'}),
    )

    loaded = read_from_persistent_store(
        'assistant:selected_moonshine_model',
        default=ns.DEFAULT_MOONSHINE_MODEL_ID,
        mapper=ns.load_moonshine_model,
    )
    assert loaded == 'medium-streaming'


def test_persisted_empty_moonshine_model_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Corrupted / empty persisted value never bricks the device."""
    from ubo_app.utils.persistent_store import read_from_persistent_store

    ns = _load_assistant(monkeypatch)
    _state_path().parent.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(json.dumps({'assistant:selected_moonshine_model': ''}))

    loaded = read_from_persistent_store(
        'assistant:selected_moonshine_model',
        default=ns.DEFAULT_MOONSHINE_MODEL_ID,
        mapper=ns.load_moonshine_model,
    )
    assert loaded == ns.DEFAULT_MOONSHINE_MODEL_ID
