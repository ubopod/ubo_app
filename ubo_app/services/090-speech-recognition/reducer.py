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
    SpeechRecognitionSetAssistantSlotsEnabledAction,
    SpeechRecognitionSetConversationEndPhrasesAction,
    SpeechRecognitionSetSelectedEngineAction,
    SpeechRecognitionSetSlotEnabledAction,
    SpeechRecognitionSetWakePhrasesAction,
    SpeechRecognitionState,
    SpeechRecognitionStatus,
    SpeechRecognitionUpdateCommandAction,
    WakeMode,
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

        case SpeechRecognitionSetSlotEnabledAction(mode=mode, enabled=enabled):
            # Conversation and Stop are coupled: toggling either sets both.
            coupled = (
                {WakeMode.CONVERSATION, WakeMode.STOP_TALKING}
                if mode in (WakeMode.CONVERSATION, WakeMode.STOP_TALKING)
                else {mode}
            )
            new_slots = tuple(
                replace(slot, enabled=enabled) if slot.mode in coupled else slot
                for slot in state.wake_slots
            )
            # Drop out of a waiting state if its triggering category was disabled.
            clear_intents = (
                not enabled
                and WakeMode.INTENTS in coupled
                and state.status is SpeechRecognitionStatus.INTENTS_WAITING
            )
            return replace(
                state,
                wake_slots=new_slots,
                status=SpeechRecognitionStatus.IDLE
                if clear_intents
                else state.status,
            )

        case SpeechRecognitionSetAssistantSlotsEnabledAction(enabled=enabled):
            assistant_modes = {
                WakeMode.QUICK_CHAT,
                WakeMode.CONVERSATION,
                WakeMode.STOP_TALKING,
            }
            return replace(
                state,
                wake_slots=tuple(
                    replace(slot, enabled=enabled)
                    if slot.mode in assistant_modes
                    else slot
                    for slot in state.wake_slots
                ),
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
            engine_name=engine_name,
        ):
            # Phrases are user-editable and live in state; match the detected
            # word (lowercased by the engine) against any phrase of an *enabled*
            # slot, case-folded.
            detected = wake_word.casefold()
            detector = engine_name or 'vosk'
            matched = next(
                (
                    slot
                    for slot in state.wake_slots
                    if slot.enabled
                    and detected in {phrase.casefold() for phrase in slot.phrases}
                ),
                None,
            )
            if (
                matched is not None
                and matched.mode is WakeMode.INTENTS
                and state.status is SpeechRecognitionStatus.IDLE
            ):
                return CompleteReducerResult(
                    state=replace(
                        state,
                        status=SpeechRecognitionStatus.INTENTS_WAITING,
                    ),
                    actions=[RgbRingSetAllAction(color=(0, 0, 255))],
                )
            if (
                matched is not None
                and matched.mode in (WakeMode.QUICK_CHAT, WakeMode.CONVERSATION)
                and state.status is SpeechRecognitionStatus.IDLE
            ):
                return CompleteReducerResult(
                    state=replace(state, status=SpeechRecognitionStatus.IDLE),
                    actions=[
                        AssistantStartListeningAction(
                            source=WakePhraseTriggerSource(
                                phrase=wake_word,
                                detector=detector,
                                mode=matched.mode,
                            ),
                        ),
                    ],
                )
            if matched is not None and matched.mode is WakeMode.STOP_TALKING:
                return CompleteReducerResult(
                    state=state,
                    actions=[
                        AssistantStopTalkingAction(
                            phrase=wake_word,
                            detector=detector,
                        ),
                    ],
                )
            return CompleteReducerResult(
                state=replace(state, status=SpeechRecognitionStatus.IDLE),
                actions=[],
            )

        case SpeechRecognitionSetWakePhrasesAction(mode=mode, phrases=phrases):
            return replace(
                state,
                wake_slots=tuple(
                    replace(slot, phrases=phrases) if slot.mode is mode else slot
                    for slot in state.wake_slots
                ),
            )

        case SpeechRecognitionSetConversationEndPhrasesAction(phrases=phrases):
            return replace(state, conversation_end_phrases=phrases)

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
