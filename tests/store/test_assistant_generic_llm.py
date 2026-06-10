"""Tests for Generic LLM assistant state behavior."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from ubo_app.store.services.assistant import (
    DEFAULT_MODELS,
    AssistantLLMName,
    GenericLLMProvider,
    _load_generic_llm_providers,
    _load_selected_models,
)

if TYPE_CHECKING:
    from types import ModuleType

    import pytest
    from redux import BaseAction

    from ubo_app.store.services.assistant import AssistantState

SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/090-assistant'


class AssistantReducer(Protocol):
    """Protocol for reducer behavior exercised by these tests."""

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
        'assistant_service_reducer',
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


def test_generic_llm_has_default_model() -> None:
    """Generic LLM has a default model entry for store serialization."""
    assert DEFAULT_MODELS[AssistantLLMName.GENERIC] == 'gpt-4.1'


def test_malformed_selected_models_falls_back_to_defaults() -> None:
    """Malformed persistent selected model data does not break state startup."""
    assert _load_selected_models('{') == DEFAULT_MODELS


def test_select_generic_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Generic LLM can be selected through the assistant reducer."""
    reducer = _load_assistant_reducer(monkeypatch)
    assistant_types = _assistant_types()
    state = cast('AssistantState', reducer(None, _init_action(reducer)))

    next_state = cast(
        'AssistantState',
        reducer(
            state,
            assistant_types.AssistantSetSelectedLLMAction(
                llm_name=assistant_types.AssistantLLMName.GENERIC,
            ),
        ),
    )

    assert isinstance(next_state, assistant_types.AssistantState)
    assert next_state.selected_llm == assistant_types.AssistantLLMName.GENERIC


def test_malformed_generic_llm_providers_falls_back_to_empty() -> None:
    """Malformed persisted provider data does not break state startup."""
    assert _load_generic_llm_providers('{') == ()
    assert _load_generic_llm_providers('{"provider_id": "x"}') == ()
    assert _load_generic_llm_providers('[{"label": "no id"}, 42]') == ()
    assert _load_generic_llm_providers(
        '[{"provider_id": "hermes", "label": "Hermes"}]',
    ) == (GenericLLMProvider(provider_id='hermes', label='Hermes'),)


def test_add_generic_llm_provider_upserts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adding a provider with an existing id replaces it instead of duplicating."""
    reducer = _load_assistant_reducer(monkeypatch)
    assistant_types = _assistant_types()
    state = cast('AssistantState', reducer(None, _init_action(reducer)))

    state = cast(
        'AssistantState',
        reducer(
            state,
            assistant_types.AssistantAddGenericLLMProviderAction(
                provider_id='hermes',
                label='Hermes',
            ),
        ),
    )
    assert state.generic_llm_providers == (
        assistant_types.GenericLLMProvider(provider_id='hermes', label='Hermes'),
    )

    state = cast(
        'AssistantState',
        reducer(
            state,
            assistant_types.AssistantAddGenericLLMProviderAction(
                provider_id='hermes',
                label='Hermes Agent',
            ),
        ),
    )
    assert state.generic_llm_providers == (
        assistant_types.GenericLLMProvider(
            provider_id='hermes',
            label='Hermes Agent',
        ),
    )


def test_select_generic_llm_provider_always_emits_changed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selecting a provider emits the changed event, even on re-select."""
    from redux import CompleteReducerResult

    reducer = _load_assistant_reducer(monkeypatch)
    assistant_types = _assistant_types()
    state = cast('AssistantState', reducer(None, _init_action(reducer)))
    state = cast(
        'AssistantState',
        reducer(
            state,
            assistant_types.AssistantAddGenericLLMProviderAction(
                provider_id='hermes',
                label='Hermes',
            ),
        ),
    )

    for _ in range(2):  # select, then re-select the same provider
        result = reducer(
            state,
            assistant_types.AssistantSelectGenericLLMProviderAction(
                provider_id='hermes',
            ),
        )
        assert isinstance(result, CompleteReducerResult)
        state = cast('AssistantState', result.state)
        assert state.selected_generic_llm_provider == 'hermes'
        assert result.events is not None
        assert any(
            isinstance(
                event,
                assistant_types.AssistantGenericLLMProviderChangedEvent,
            )
            and event.provider_id == 'hermes'
            for event in result.events
        )


def test_remove_non_selected_generic_llm_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Removing a non-selected provider leaves the selection untouched."""
    from redux import CompleteReducerResult

    reducer = _load_assistant_reducer(monkeypatch)
    assistant_types = _assistant_types()
    state = cast('AssistantState', reducer(None, _init_action(reducer)))
    for provider_id in ('hermes', 'other'):
        state = cast(
            'AssistantState',
            reducer(
                state,
                assistant_types.AssistantAddGenericLLMProviderAction(
                    provider_id=provider_id,
                    label=provider_id,
                ),
            ),
        )
    result = reducer(
        state,
        assistant_types.AssistantSelectGenericLLMProviderAction(
            provider_id='other',
        ),
    )
    state = cast('AssistantState', cast('CompleteReducerResult', result).state)

    result = reducer(
        state,
        assistant_types.AssistantRemoveGenericLLMProviderAction(
            provider_id='hermes',
        ),
    )
    assert isinstance(result, CompleteReducerResult)
    state = cast('AssistantState', result.state)
    assert state.generic_llm_providers == (
        assistant_types.GenericLLMProvider(provider_id='other', label='other'),
    )
    assert state.selected_generic_llm_provider == 'other'
    assert result.events is not None
    assert any(
        isinstance(event, assistant_types.AssistantGenericLLMProviderRemovedEvent)
        and event.provider_id == 'hermes'
        and event.was_selected is False
        for event in result.events
    )


def test_remove_selected_generic_llm_provider_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Removing the selected provider clears selection and leaves GENERIC."""
    from redux import CompleteReducerResult

    reducer = _load_assistant_reducer(monkeypatch)
    assistant_types = _assistant_types()
    state = cast('AssistantState', reducer(None, _init_action(reducer)))
    state = cast(
        'AssistantState',
        reducer(
            state,
            assistant_types.AssistantAddGenericLLMProviderAction(
                provider_id='hermes',
                label='Hermes',
            ),
        ),
    )
    result = reducer(
        state,
        assistant_types.AssistantSelectGenericLLMProviderAction(
            provider_id='hermes',
        ),
    )
    state = cast('AssistantState', cast('CompleteReducerResult', result).state)
    state = cast(
        'AssistantState',
        reducer(
            state,
            assistant_types.AssistantSetSelectedLLMAction(
                llm_name=assistant_types.AssistantLLMName.GENERIC,
            ),
        ),
    )

    result = reducer(
        state,
        assistant_types.AssistantRemoveGenericLLMProviderAction(
            provider_id='hermes',
        ),
    )
    assert isinstance(result, CompleteReducerResult)
    state = cast('AssistantState', result.state)
    assert state.generic_llm_providers == ()
    assert state.selected_generic_llm_provider == ''
    assert state.selected_llm == assistant_types.AssistantLLMName.OLLAMA
    assert result.events is not None
    assert any(
        isinstance(event, assistant_types.AssistantGenericLLMProviderRemovedEvent)
        and event.provider_id == 'hermes'
        and event.was_selected is True
        for event in result.events
    )


def test_set_generic_llm_model_without_selecting_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider setup can store Generic LLM model independent of current selection."""
    from redux import CompleteReducerResult

    reducer = _load_assistant_reducer(monkeypatch)
    assistant_types = _assistant_types()
    state = cast('AssistantState', reducer(None, _init_action(reducer)))

    result = reducer(
        state,
        assistant_types.AssistantSetSelectedModelAction(
            llm_name=assistant_types.AssistantLLMName.GENERIC,
            model='provider/model',
        ),
    )
    # Reducer emits AssistantModelChangedEvent alongside the state update,
    # so it returns a CompleteReducerResult wrapping both.
    assert isinstance(result, CompleteReducerResult)
    next_state = cast('AssistantState', result.state)

    assert isinstance(next_state, assistant_types.AssistantState)
    assert next_state.selected_llm == assistant_types.AssistantLLMName.OLLAMA
    assert (
        next_state.selected_models[assistant_types.AssistantLLMName.GENERIC]
        == 'provider/model'
    )
    assert result.events is not None
    assert any(
        isinstance(e, assistant_types.AssistantModelChangedEvent)
        and e.llm_name == assistant_types.AssistantLLMName.GENERIC
        and e.model == 'provider/model'
        for e in result.events
    )
