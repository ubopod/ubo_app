# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import replace

from redux import CompleteReducerResult, InitAction, InitializationActionError

from ubo_app.store.services.speech_synthesis import (
    SpeechSynthesisAction,
    SpeechSynthesisEvent,
    SpeechSynthesisReadTextAction,
    SpeechSynthesisSetEngineAction,
    SpeechSynthesisState,
    SpeechSynthesisSynthesizeTextEvent,
    SpeechSynthesisUpdateAccessKeyStatus,
)


def reducer(
    state: SpeechSynthesisState | None,
    action: SpeechSynthesisAction,
) -> (
    SpeechSynthesisState
    | CompleteReducerResult[
        SpeechSynthesisState, SpeechSynthesisAction, SpeechSynthesisEvent,
    ]
):
    if state is None:
        if isinstance(action, InitAction):
            return SpeechSynthesisState()
        raise InitializationActionError(action)

    if isinstance(action, SpeechSynthesisUpdateAccessKeyStatus):
        return replace(state, is_access_key_set=action.is_access_key_set)

    if isinstance(action, SpeechSynthesisSetEngineAction):
        return replace(state, selected_engine=action.engine)

    if isinstance(action, SpeechSynthesisReadTextAction):
        return CompleteReducerResult(
            state=state,
            events=[
                SpeechSynthesisSynthesizeTextEvent(
                    information=action.information,
                    speech_rate=action.speech_rate,
                ),
            ],
        )

    return state
