"""Store behavior of the AUTO (per-prompt routing) LLM selection.

Uses the same ``importlib`` discipline as ``test_assistant_run_pipeline_event.py``
so the suite survives the ``sys.modules`` wipe integration tests perform.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import pytest
    from redux import BaseAction

    from ubo_app.store.services.assistant import (
        AssistantRunPipelineEvent,
        AssistantState,
    )

SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/090-assistant'


def _load(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())

    from ubo_app.store.services import assistant as assistant_module

    assistant_module = importlib.reload(assistant_module)

    spec = importlib.util.spec_from_file_location(
        'assistant_service_reducer_auto_llm',
        SERVICE_PATH / 'reducer.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    return SimpleNamespace(reducer=module.reducer, assistant=assistant_module)


def _initial_state(ns: SimpleNamespace) -> AssistantState:
    init_action = cast('type[BaseAction]', ns.reducer.__globals__['InitAction'])()
    return cast('AssistantState', ns.reducer(None, init_action))


def _state(result: object) -> AssistantState:
    from redux import CompleteReducerResult

    if isinstance(result, CompleteReducerResult):
        return cast('AssistantState', result.state)
    return cast('AssistantState', result)


def _run_pipeline_event(
    ns: SimpleNamespace,
    result: object,
) -> AssistantRunPipelineEvent:
    from redux import CompleteReducerResult

    assert isinstance(result, CompleteReducerResult)
    assert result.events is not None
    return cast(
        'AssistantRunPipelineEvent',
        next(
            event
            for event in result.events
            if isinstance(event, ns.assistant.AssistantRunPipelineEvent)
        ),
    )


def test_auto_is_the_last_enum_member(monkeypatch: pytest.MonkeyPatch) -> None:
    """The proto generator numbers enum values in order; AUTO must append."""
    ns = _load(monkeypatch)

    assert list(ns.assistant.AssistantLLMName)[-1] == ns.assistant.AssistantLLMName.AUTO


def test_selecting_auto_records_the_previous_provider_as_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Switching to AUTO remembers the provider that was in use."""
    ns = _load(monkeypatch)
    a = ns.assistant
    state = replace(_initial_state(ns), selected_llm=a.AssistantLLMName.ANTHROPIC)

    state = _state(
        ns.reducer(
            state,
            a.AssistantSetSelectedLLMAction(llm_name=a.AssistantLLMName.AUTO),
        ),
    )

    assert state.selected_llm == a.AssistantLLMName.AUTO
    assert state.auto_fallback_llm == a.AssistantLLMName.ANTHROPIC


def test_reselecting_auto_keeps_the_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """AUTO → AUTO never makes AUTO its own fallback."""
    ns = _load(monkeypatch)
    a = ns.assistant
    state = replace(
        _initial_state(ns),
        selected_llm=a.AssistantLLMName.AUTO,
        auto_fallback_llm=a.AssistantLLMName.OPENAI,
    )

    state = _state(
        ns.reducer(
            state,
            a.AssistantSetSelectedLLMAction(llm_name=a.AssistantLLMName.AUTO),
        ),
    )

    assert state.auto_fallback_llm == a.AssistantLLMName.OPENAI


def test_selecting_a_provider_leaves_the_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Leaving AUTO doesn't touch the remembered fallback."""
    ns = _load(monkeypatch)
    a = ns.assistant
    state = replace(
        _initial_state(ns),
        selected_llm=a.AssistantLLMName.AUTO,
        auto_fallback_llm=a.AssistantLLMName.OPENAI,
    )

    state = _state(
        ns.reducer(
            state,
            a.AssistantSetSelectedLLMAction(llm_name=a.AssistantLLMName.GROK),
        ),
    )

    assert state.selected_llm == a.AssistantLLMName.GROK
    assert state.auto_fallback_llm == a.AssistantLLMName.OPENAI


def test_one_shot_request_uses_the_fallback_instead_of_auto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Programmatic requests are not routed; they get AUTO's fallback and model."""
    ns = _load(monkeypatch)
    a = ns.assistant
    state = replace(
        _initial_state(ns),
        selected_llm=a.AssistantLLMName.AUTO,
        auto_fallback_llm=a.AssistantLLMName.ANTHROPIC,
        selected_models={a.AssistantLLMName.ANTHROPIC: 'claude-test-model'},
    )

    event = _run_pipeline_event(
        ns,
        ns.reducer(
            state,
            a.AssistantCompleteAction(text='what is 2+2?', session_id='s1'),
        ),
    )

    assert event.llm_provider == a.AssistantLLMName.ANTHROPIC
    assert event.llm_model == 'claude-test-model'


def test_removing_the_generic_fallback_resets_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A removed generic provider can't stay AUTO's fallback."""
    ns = _load(monkeypatch)
    a = ns.assistant
    state = replace(
        _initial_state(ns),
        selected_llm=a.AssistantLLMName.AUTO,
        auto_fallback_llm=a.AssistantLLMName.GENERIC,
        generic_llm_providers=(
            a.GenericLLMProvider(provider_id='hermes', label='Hermes'),
        ),
        selected_generic_llm_provider='hermes',
    )

    state = _state(
        ns.reducer(
            state,
            a.AssistantRemoveGenericLLMProviderAction(provider_id='hermes'),
        ),
    )

    assert state.selected_llm == a.AssistantLLMName.AUTO
    assert state.auto_fallback_llm == a.AssistantLLMName.OLLAMA
