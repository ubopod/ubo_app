# ruff: noqa: D100, D103
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from redux import CompleteReducerResult, InitializationActionError
from redux.basic_types import InitAction

from ubo_app.store.services.assistant import (
    AssistantAction,
    AssistantDownloadOllamaModelAction,
    AssistantDownloadOllamaModelEvent,
    AssistantEvent,
    AssistantReportAction,
    AssistantReportEvent,
    AssistantSetIsActiveAction,
    AssistantSetSelectedLLMAction,
    AssistantSetSelectedModelAction,
    AssistantState,
)

if TYPE_CHECKING:
    from redux import ReducerResult


def reducer(
    state: AssistantState | None,
    action: AssistantAction,
) -> ReducerResult[AssistantState, None, AssistantEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return AssistantState()

        raise InitializationActionError(action)

    if isinstance(action, AssistantSetIsActiveAction):
        return replace(state, is_active=action.is_active)

    if isinstance(action, AssistantSetSelectedLLMAction):
        return replace(state, selected_llm=action.llm_name)

    if isinstance(action, AssistantSetSelectedModelAction):
        return replace(
            state,
            selected_models={
                **state.selected_models,
                state.selected_llm: action.model,
            },
        )

    if isinstance(action, AssistantDownloadOllamaModelAction):
        return CompleteReducerResult(
            state=state,
            events=[AssistantDownloadOllamaModelEvent(model=action.model)],
        )

    if isinstance(action, AssistantReportAction):
        return CompleteReducerResult(
            state=state,
            events=[
                AssistantReportEvent(
                    source_id=action.source_id,
                    data=action.data,
                ),
            ],
        )

    return state
