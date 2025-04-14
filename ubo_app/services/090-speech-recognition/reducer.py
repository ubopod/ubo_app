# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from redux import InitAction, InitializationActionError

from ubo_app.store.services.speech_recognition import (
    SpeechRecognitionAction,
    SpeechRecognitionSetIsActiveAction,
    SpeechRecognitionState,
)

if TYPE_CHECKING:
    from redux import ReducerResult


def reducer(
    state: SpeechRecognitionState | None,
    action: SpeechRecognitionAction,
) -> ReducerResult[SpeechRecognitionState, None, None]:
    if state is None:
        if isinstance(action, InitAction):
            return SpeechRecognitionState()

        raise InitializationActionError(action)

    if isinstance(action, SpeechRecognitionSetIsActiveAction):
        return replace(state, is_active=action.is_active)

    return state
