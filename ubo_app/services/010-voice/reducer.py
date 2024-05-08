# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from redux import CompleteReducerResult, InitAction, InitializationActionError

from ubo_app.store.services.voice import (
    VoiceAction,
    VoiceEvent,
    VoiceReadTextAction,
    VoiceState,
    VoiceSynthesizeTextEvent,
)


def reducer(
    state: VoiceState | None,
    action: VoiceAction,
) -> VoiceState | CompleteReducerResult[VoiceState, VoiceAction, VoiceEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return VoiceState()
        raise InitializationActionError(action)

    if isinstance(action, VoiceReadTextAction):
        return CompleteReducerResult(
            state=state,
            events=[
                VoiceSynthesizeTextEvent(
                    text=action.text,
                    speech_rate=action.speech_rate,
                ),
            ],
        )

    return state
