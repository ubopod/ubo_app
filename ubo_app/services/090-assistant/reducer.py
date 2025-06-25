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
    AssistantProcessSpeechEvent,
    AssistantSetIsActiveAction,
    AssistantSetSelectedEngineAction,
    AssistantSetSelectedModelAction,
    AssistantState,
)
from ubo_app.store.services.speech_recognition import (
    SpeechRecognitionReportSpeechAction,
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

    if isinstance(action, AssistantSetSelectedEngineAction):
        return replace(state, selected_engine=action.engine_name)

    if isinstance(action, AssistantSetSelectedModelAction):
        return replace(
            state,
            selected_models={
                **state.selected_models,
                state.selected_engine: action.model,
            },
        )

    if isinstance(action, AssistantDownloadOllamaModelAction):
        return CompleteReducerResult(
            state=state,
            events=[AssistantDownloadOllamaModelEvent(model=action.model)],
        )

    if isinstance(action, SpeechRecognitionReportSpeechAction):
        return CompleteReducerResult(
            state=state,
            events=[
                AssistantProcessSpeechEvent(
                    audio=action.audio,
                    text=action.text,
                ),
            ],
        )

    return state
