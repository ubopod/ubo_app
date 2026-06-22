# ruff: noqa: D100, D103
from __future__ import annotations

from dataclasses import replace

from redux import CompleteReducerResult, InitAction, InitializationActionError

from ubo_app.store.services.speech_synthesis import (
    SpeechSynthesisAction,
    SpeechSynthesisEvent,
    SpeechSynthesisReadTextAction,
    SpeechSynthesisSetIsEnabledAction,
    SpeechSynthesisSetPreferLocalAction,
    SpeechSynthesisState,
    SpeechSynthesisSynthesizeTextEvent,
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
        case SpeechSynthesisSetIsEnabledAction():
            return replace(state, is_screen_reader_enabled=action.is_enabled)

        case SpeechSynthesisSetPreferLocalAction():
            return replace(state, is_prefer_local_enabled=action.is_enabled)

        case SpeechSynthesisReadTextAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    SpeechSynthesisSynthesizeTextEvent(
                        information=action.information,
                    ),
                ],
            )

        case _:
            return state
