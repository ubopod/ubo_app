# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import replace

from redux import CompleteReducerResult, InitAction, InitializationActionError

from ubo_app.store.services.voice import (
    VoiceAction,
    VoiceEvent,
    VoiceReadTextAction,
    VoiceSetEngineAction,
    VoiceState,
    VoiceSynthesizeTextEvent,
    VoiceUpdateAccessKeyStatus,
)


def reducer(
    state: VoiceState | None,
    action: VoiceAction,
) -> VoiceState | CompleteReducerResult[VoiceState, VoiceAction, VoiceEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return VoiceState()
        raise InitializationActionError(action)

    if isinstance(action, VoiceUpdateAccessKeyStatus):
        return replace(state, is_access_key_set=action.is_access_key_set)

    if isinstance(action, VoiceSetEngineAction):
        return replace(state, selected_engine=action.engine)

    if isinstance(action, VoiceReadTextAction):
        return CompleteReducerResult(
            state=state,
            events=[
                VoiceSynthesizeTextEvent(
                    text=action.text,
                    piper_text=action.piper_text or action.text,
                    picovoice_text=action.picovoice_text or action.text,
                    speech_rate=action.speech_rate,
                ),
            ],
        )

    return state
