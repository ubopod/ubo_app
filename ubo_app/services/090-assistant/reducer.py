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
    AssistantStartListeningAction,
    AssistantState,
    AssistantStopListeningAction,
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

    match action:
        case AssistantSetIsActiveAction():
            return replace(state, is_active=action.is_active)

        case AssistantSetSelectedLLMAction():
            return replace(state, selected_llm=action.llm_name)

        case AssistantSetSelectedModelAction():
            return replace(
                state,
                selected_models={
                    **state.selected_models,
                    state.selected_llm: action.model,
                },
            )

        case AssistantDownloadOllamaModelAction():
            return CompleteReducerResult(
                state=state,
                events=[AssistantDownloadOllamaModelEvent(model=action.model)],
            )

        case AssistantReportAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    AssistantReportEvent(
                        source_id=action.source_id,
                        data=action.data,
                    ),
                ],
            )

        case AssistantStartListeningAction():
            return state(is_listening=True)

        case AssistantStopListeningAction():
            return state(is_listening=False)

        case _:
            return state
