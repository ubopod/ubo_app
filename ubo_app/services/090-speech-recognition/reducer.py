# ruff: noqa: D100, D103
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from commands import load_or_seed_commands
from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
)

from ubo_app.constants.assistant import (
    ASSISTANT_CONVERSATION_WAKE_WORD,
    ASSISTANT_QUICK_CHAT_WAKE_PHRASE,
    ASSISTANT_STOP_TALKING_PHRASE,
    INTENTS_WAKE_WORD,
)
from ubo_app.store.services.assistant import (
    AssistantStartListeningAction,
    AssistantStopTalkingAction,
    WakePhraseTriggerSource,
)
from ubo_app.store.services.rgb_ring import (
    RgbRingBlankAction,
    RgbRingSetAllAction,
)
from ubo_app.store.services.speech_recognition import (
    SpeechRecognitionAction,
    SpeechRecognitionAddCommandAction,
    SpeechRecognitionBoundActionTriggeredEvent,
    SpeechRecognitionIntent,
    SpeechRecognitionRemoveCommandAction,
    SpeechRecognitionReportIntentDetectionAction,
    SpeechRecognitionReportIntentTimeoutAction,
    SpeechRecognitionReportSpeechAction,
    SpeechRecognitionReportWakeWordDetectionAction,
    SpeechRecognitionSetIsAssistantActiveAction,
    SpeechRecognitionSetIsIntentsActiveAction,
    SpeechRecognitionSetSelectedEngineAction,
    SpeechRecognitionState,
    SpeechRecognitionStatus,
    SpeechRecognitionUpdateCommandAction,
)

if TYPE_CHECKING:
    from redux import ReducerResult

    from ubo_app.store.main import UboAction


ACKNOWLEDGMENT_ACTION = RgbRingBlankAction()


def reducer(
    state: SpeechRecognitionState | None,
    action: SpeechRecognitionAction,
) -> ReducerResult[
    SpeechRecognitionState,
    UboAction,
    SpeechRecognitionBoundActionTriggeredEvent,
]:
    if state is None:
        if isinstance(action, InitAction):
            return SpeechRecognitionState(intents=load_or_seed_commands())

        raise InitializationActionError(action)

    match action:
        case SpeechRecognitionSetSelectedEngineAction():
            return replace(
                state,
                selected_engine=action.engine_name,
                status=SpeechRecognitionStatus.IDLE,
            )

        case SpeechRecognitionSetIsIntentsActiveAction():
            return replace(
                state,
                is_intents_active=action.is_active,
                status=SpeechRecognitionStatus.IDLE
                if state.status is SpeechRecognitionStatus.INTENTS_WAITING
                else state.status,
            )

        case SpeechRecognitionSetIsAssistantActiveAction():
            return replace(
                state,
                is_assistant_active=action.is_active,
                status=SpeechRecognitionStatus.IDLE
                if state.status is SpeechRecognitionStatus.ASSISTANT_WAITING
                else state.status,
            )

        case SpeechRecognitionAddCommandAction():
            return replace(
                state,
                intents=[
                    *state.intents,
                    SpeechRecognitionIntent(
                        id=action.id,
                        label=action.label,
                        phrases=action.phrases,
                        action_keys=action.action_keys,
                    ),
                ],
            )

        case SpeechRecognitionUpdateCommandAction():
            return replace(
                state,
                intents=[
                    SpeechRecognitionIntent(
                        id=action.id,
                        label=action.label,
                        phrases=action.phrases,
                        action_keys=action.action_keys,
                    )
                    if intent.id == action.id
                    else intent
                    for intent in state.intents
                ],
            )

        case SpeechRecognitionRemoveCommandAction():
            return replace(
                state,
                intents=[
                    intent for intent in state.intents if intent.id != action.id
                ],
            )

        case SpeechRecognitionReportWakeWordDetectionAction(
            wake_word=wake_word,
        ):
            if (
                wake_word == INTENTS_WAKE_WORD
                and state.status is SpeechRecognitionStatus.IDLE
            ):
                new_status = SpeechRecognitionStatus.INTENTS_WAITING
                return CompleteReducerResult(
                    state=replace(state, status=new_status),
                    actions=[RgbRingSetAllAction(color=(0, 0, 255))],
                )
            if (
                wake_word
                in (
                    ASSISTANT_QUICK_CHAT_WAKE_PHRASE,
                    ASSISTANT_CONVERSATION_WAKE_WORD,
                )
                and state.status is SpeechRecognitionStatus.IDLE
            ):
                return CompleteReducerResult(
                    state=replace(state, status=SpeechRecognitionStatus.IDLE),
                    actions=[
                        AssistantStartListeningAction(
                            source=WakePhraseTriggerSource(phrase=wake_word),
                        ),
                    ],
                )
            if wake_word == ASSISTANT_STOP_TALKING_PHRASE:
                return CompleteReducerResult(
                    state=state,
                    actions=[AssistantStopTalkingAction()],
                )
            return CompleteReducerResult(
                state=replace(state, status=SpeechRecognitionStatus.IDLE),
                actions=[],
            )

        case SpeechRecognitionReportIntentDetectionAction():
            # Stay pure: emit the event and let the service handler resolve the
            # action keys against the bindable-actions registry and dispatch
            # them (with the acknowledgment sequence).
            return CompleteReducerResult(
                state=replace(state, status=SpeechRecognitionStatus.IDLE),
                events=[
                    SpeechRecognitionBoundActionTriggeredEvent(
                        action_keys=action.intent.action_keys,
                        phrase=action.text,
                    ),
                ],
            )

        case SpeechRecognitionReportIntentTimeoutAction():
            # No command was recognised within the listening window; leave
            # listening mode and clear the listening indicator.
            if state.status is SpeechRecognitionStatus.INTENTS_WAITING:
                return CompleteReducerResult(
                    state=replace(state, status=SpeechRecognitionStatus.IDLE),
                    actions=[ACKNOWLEDGMENT_ACTION],
                )
            return state

        case SpeechRecognitionReportSpeechAction():
            return CompleteReducerResult(
                state=replace(state, status=SpeechRecognitionStatus.IDLE),
                actions=[ACKNOWLEDGMENT_ACTION],
            )

        case _:
            return state
