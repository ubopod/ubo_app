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
    AssistantSetActiveEngineAction,
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

    if isinstance(action, AssistantSetActiveEngineAction):
        return replace(state, active_engine=action.engine)

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
                    raw_audio=action.raw_audio,
                    text=action.text,
                ),
            ],
        )

    return state
