# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, TypeAlias

from redux import CompleteReducerResult, InitializationActionError
from redux.basic_types import InitAction

from ubo_app.store.services.assistant import (
    AssistantDownloadOllamaModelAction,
    AssistantDownloadOllamaModelEvent,
    AssistantEvent,
    AssistantProcessSpeechEvent,
    AssistantSetSelectedEngineAction,
    AssistantState,
)
from ubo_app.store.services.speech_recognition import (
    SpeechRecognitionReportSpeechAction,
)

if TYPE_CHECKING:
    from redux import ReducerResult

Action: TypeAlias = InitAction | SpeechRecognitionReportSpeechAction


def reducer(
    state: AssistantState | None,
    action: Action,
) -> ReducerResult[AssistantState, None, AssistantEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return AssistantState()

        raise InitializationActionError(action)

    if isinstance(action, AssistantSetSelectedEngineAction):
        return replace(state, selected_engine=action.engine_name)

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
