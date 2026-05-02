"""Tests for Generic LLM assistant state behavior."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from redux.basic_types import InitAction

from ubo_app.store.services.assistant import (
    DEFAULT_MODELS,
    AssistantLLMName,
    AssistantSetSelectedLLMAction,
    AssistantSetSelectedModelAction,
    AssistantState,
    _load_selected_models,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/090-assistant'


def _load_assistant_reducer(monkeypatch: pytest.MonkeyPatch) -> Callable[..., object]:
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
    return module.reducer


def test_generic_llm_has_default_model() -> None:
    """Generic LLM has a default model entry for store serialization."""
    assert DEFAULT_MODELS[AssistantLLMName.GENERIC] == 'gpt-4.1'


def test_malformed_selected_models_falls_back_to_defaults() -> None:
    """Malformed persistent selected model data does not break state startup."""
    assert _load_selected_models('{') == DEFAULT_MODELS


def test_select_generic_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Generic LLM can be selected through the assistant reducer."""
    reducer = _load_assistant_reducer(monkeypatch)
    state = reducer(None, InitAction())

    next_state = reducer(
        state,
        AssistantSetSelectedLLMAction(llm_name=AssistantLLMName.GENERIC),
    )

    assert isinstance(next_state, AssistantState)
    assert next_state.selected_llm == AssistantLLMName.GENERIC


def test_set_generic_llm_model_without_selecting_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider setup can store Generic LLM model independent of current selection."""
    reducer = _load_assistant_reducer(monkeypatch)
    state = reducer(None, InitAction())

    next_state = reducer(
        state,
        AssistantSetSelectedModelAction(
            llm_name=AssistantLLMName.GENERIC,
            model='provider/model',
        ),
    )

    assert isinstance(next_state, AssistantState)
    assert next_state.selected_llm == AssistantLLMName.OLLAMA
    assert next_state.selected_models[AssistantLLMName.GENERIC] == 'provider/model'
