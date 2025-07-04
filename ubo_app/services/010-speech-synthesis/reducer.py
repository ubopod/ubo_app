# ruff: noqa: D100, D103
from __future__ import annotations

from dataclasses import replace

from redux import CompleteReducerResult, InitAction, InitializationActionError

from ubo_app.store.services.speech_synthesis import (
    SpeechSynthesisAction,
    SpeechSynthesisEvent,
    SpeechSynthesisReadTextAction,
    SpeechSynthesisSetSelectedEngineAction,
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
        SpeechSynthesisState,
        SpeechSynthesisAction,
        SpeechSynthesisEvent,
    ]
):
    if state is None:
        if isinstance(action, InitAction):
            return SpeechSynthesisState()
        raise InitializationActionError(action)

    match action:
        case SpeechSynthesisUpdateAccessKeyStatus():
            return replace(state, is_access_key_set=action.is_access_key_set)

        case SpeechSynthesisSetSelectedEngineAction():
            return replace(state, selected_engine=action.engine_name)

        case SpeechSynthesisReadTextAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    SpeechSynthesisSynthesizeTextEvent(
                        information=action.information,
                        speech_rate=action.speech_rate,
                    ),
                ],
            )

        case _:
            return state
