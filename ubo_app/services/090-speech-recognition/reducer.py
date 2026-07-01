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
    SpeechRecognitionSetAssistantEnabledAction,
    SpeechRecognitionSetConversationEndPhrasesAction,
    SpeechRecognitionState,
    SpeechRecognitionStatus,
    SpeechRecognitionTriggerModeAction,
    SpeechRecognitionUpdateCommandAction,
    WakeEngineSetEnabledAction,
    WakeMode,
    WakeTriggerAddAction,
    WakeTriggerRemoveAction,
    WakeWordDeleteModelAction,
    WakeWordDeleteModelEvent,
    WakeWordDownloadModelsAction,
    WakeWordDownloadModelsEvent,
    WakeWordEngineName,
    WakeWordModelStatus,
    WakeWordSetAvailableModelsAction,
    WakeWordSetModelsStatusAction,
    WakeWordTrigger,
    clamp_sensitivity,
    model_status,
    set_model_status,
    trigger_by_id,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from redux import ReducerResult

    from ubo_app.store.main import UboAction


ACKNOWLEDGMENT_ACTION = RgbRingBlankAction()

_ASSISTANT_MODES = (WakeMode.QUICK_CHAT, WakeMode.CONVERSATION)


def _map_engine_triggers(
    state: SpeechRecognitionState,
    engine: WakeWordEngineName,
    transform: Callable[
        [tuple[WakeWordTrigger, ...]],
        tuple[WakeWordTrigger, ...],
    ],
) -> SpeechRecognitionState:
    """Return *state* with *engine*'s triggers replaced by ``transform(triggers)``."""
    return replace(
        state,
        wake_engines=tuple(
            replace(config, triggers=transform(config.triggers))
            if config.engine is engine
            else config
            for config in state.wake_engines
        ),
    )


def _apply_wake_mode(
    state: SpeechRecognitionState,
    mode: WakeMode,
    phrase: str,
    detector: str,
    *,
    enforce_assistant_gate: bool = True,
) -> CompleteReducerResult[
    SpeechRecognitionState,
    UboAction,
    SpeechRecognitionBoundActionTriggeredEvent
    | WakeWordDownloadModelsEvent
    | WakeWordDeleteModelEvent,
]:
    """Map a triggered wake *mode* to its assistant effect.

    Shared by audio-stream detections (`SpeechRecognitionReportWakeWordDetection
    Action`) and Infrared-bound triggers (`SpeechRecognitionTriggerModeAction`):
    INTENTS arms the command listener (blue ring) when idle; QUICK_CHAT/
    CONVERSATION start the assistant when idle; STOP_TALKING stops it talking.

    ``enforce_assistant_gate`` makes the master ``assistant_enabled`` switch
    authoritative here in the (pure) reducer for QUICK_CHAT/CONVERSATION: the
    audio-detection path enforces it (a direct, e.g. remote-dispatched, detection
    can't start the assistant while it's off), while the Infrared-bound path
    passes ``False`` so an explicit remote-key binding stays an intentional
    override (mirrors ``commands.py:_trigger_mode``). The EnginesManager's
    trigger-dropping when the switch is off is now just an optimization, not the
    sole enforcement.
    """
    if (
        mode is WakeMode.INTENTS
        and state.status is SpeechRecognitionStatus.IDLE
    ):
        return CompleteReducerResult(
            state=replace(state, status=SpeechRecognitionStatus.INTENTS_WAITING),
            actions=[RgbRingSetAllAction(color=(0, 0, 255))],
        )
    if (
        mode in _ASSISTANT_MODES
        and enforce_assistant_gate
        and not state.assistant_enabled
    ):
        # Assistant master switch is off — swallow the wake without starting it.
        return CompleteReducerResult(
            state=replace(state, status=SpeechRecognitionStatus.IDLE),
            actions=[],
        )
    if (
        mode in _ASSISTANT_MODES
        and state.status is SpeechRecognitionStatus.IDLE
    ):
        return CompleteReducerResult(
            state=replace(state, status=SpeechRecognitionStatus.IDLE),
            actions=[
                AssistantStartListeningAction(
                    source=WakePhraseTriggerSource(
                        phrase=phrase,
                        detector=detector,
                        mode=mode,
                    ),
                ),
            ],
        )
    if mode is WakeMode.STOP_TALKING:
        return CompleteReducerResult(
            state=state,
            actions=[
                AssistantStopTalkingAction(phrase=phrase, detector=detector),
            ],
        )
    return CompleteReducerResult(
        state=replace(state, status=SpeechRecognitionStatus.IDLE),
        actions=[],
    )


def reducer(
    state: SpeechRecognitionState | None,
    action: SpeechRecognitionAction,
) -> ReducerResult[
    SpeechRecognitionState,
    UboAction,
    SpeechRecognitionBoundActionTriggeredEvent
    | WakeWordDownloadModelsEvent
    | WakeWordDeleteModelEvent,
]:
    if state is None:
        if isinstance(action, InitAction):
            return SpeechRecognitionState(intents=load_or_seed_commands())

        raise InitializationActionError(action)

    match action:
        # --- wake engine / trigger configuration ---------------------------

        case WakeEngineSetEnabledAction(engine=engine, enabled=enabled):
            return replace(
                state,
                wake_engines=tuple(
                    replace(config, enabled=enabled)
                    if config.engine is engine
                    else config
                    for config in state.wake_engines
                ),
            )

        case WakeTriggerAddAction(
            engine=engine,
            id=trigger_id,
            label=label,
            mode=mode,
            value=value,
            sensitivity=sensitivity,
        ):
            trigger = WakeWordTrigger(
                id=trigger_id,
                label=label,
                mode=mode,
                value=value,
                # Untrusted (a remote client can dispatch this) — clamp to [0,1].
                sensitivity=clamp_sensitivity(sensitivity),
            )
            return _map_engine_triggers(
                state,
                engine,
                lambda triggers: (*triggers, trigger),
            )

        case WakeTriggerRemoveAction(engine=engine, id=trigger_id):
            return _map_engine_triggers(
                state,
                engine,
                lambda triggers: tuple(
                    trigger for trigger in triggers if trigger.id != trigger_id
                ),
            )

        case SpeechRecognitionSetAssistantEnabledAction(enabled=enabled):
            return replace(state, assistant_enabled=enabled)

        # --- voice commands (intents) --------------------------------------

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

        # --- wake-word detection -> assistant policy -----------------------

        case SpeechRecognitionReportWakeWordDetectionAction(
            engine_name=engine_name,
            trigger_id=trigger_id,
            phrase=phrase,
        ):
            try:
                engine = WakeWordEngineName(engine_name)
            except ValueError:
                engine = None
            trigger = (
                trigger_by_id(state, engine, trigger_id)
                if engine is not None
                else None
            )
            if trigger is None:
                return CompleteReducerResult(
                    state=replace(state, status=SpeechRecognitionStatus.IDLE),
                    actions=[],
                )
            # Forward the trigger's human-readable label (not its engine-specific
            # value, which for OpenWakeWord is a model stem like ``hey_jarvis_v0.1``)
            # to the assistant trigger source / mic-buffer metadata.
            return _apply_wake_mode(
                state,
                trigger.mode,
                trigger.label or phrase or trigger.value,
                engine_name or 'vosk',
            )

        case SpeechRecognitionTriggerModeAction(
            mode=mode,
            phrase=phrase,
            detector=detector,
        ):
            # Infrared-bound override: an explicit remote key fires the mode even
            # when the assistant master switch is off (see commands.py:_trigger_mode).
            return _apply_wake_mode(
                state,
                mode,
                phrase,
                detector,
                enforce_assistant_gate=False,
            )

        case SpeechRecognitionSetConversationEndPhrasesAction(phrases=phrases):
            return replace(state, conversation_end_phrases=phrases)

        # --- wake-word model lifecycle -------------------------------------

        case WakeWordDownloadModelsAction(engine_name=engine_name):
            # Idempotent at the boundary: a re-dispatch while a download is already
            # in flight (e.g. a remote/direct dispatch that bypasses the menu's UI
            # guard) must not emit a second event and launch an overlapping loop.
            if model_status(state, engine_name) is WakeWordModelStatus.DOWNLOADING:
                return state
            # Stay pure: mark the engine as downloading and let the service
            # handler perform the actual (blocking) download off the loop.
            return CompleteReducerResult(
                state=replace(
                    state,
                    wake_word_models_status=set_model_status(
                        state.wake_word_models_status,
                        engine_name,
                        WakeWordModelStatus.DOWNLOADING,
                    ),
                ),
                events=[WakeWordDownloadModelsEvent(engine_name=engine_name)],
            )

        case WakeWordSetModelsStatusAction(
            engine_name=engine_name,
            status=status,
        ):
            return replace(
                state,
                wake_word_models_status=set_model_status(
                    state.wake_word_models_status,
                    engine_name,
                    status,
                ),
            )

        case WakeWordSetAvailableModelsAction(engine=engine, models=models):
            if engine is WakeWordEngineName.OPENWAKEWORD:
                return replace(state, openwakeword_models=models)
            return state

        case WakeWordDeleteModelAction(engine=engine, model_id=model_id):
            # Only OpenWakeWord has a deletable on-disk model pool. Guard the
            # engine so a malformed/remote action with the wrong engine can't
            # mutate ``openwakeword_models`` (or prune the wrong engine's triggers)
            # while the file-deleting event is dropped service-side.
            if engine is not WakeWordEngineName.OPENWAKEWORD:
                return state
            # Authorize against the known pool: a remote/client-dispatched action
            # must not delete an arbitrary id (e.g. a shared helper model). Only
            # ids present in ``openwakeword_models`` are deletable.
            if model_id not in state.openwakeword_models:
                return state
            # Drop the model from the pool + any trigger referencing it; delete
            # the file off-reducer via the event.
            pruned = _map_engine_triggers(
                replace(
                    state,
                    openwakeword_models=tuple(
                        stem
                        for stem in state.openwakeword_models
                        if stem != model_id
                    ),
                ),
                engine,
                lambda triggers: tuple(
                    trigger for trigger in triggers if trigger.value != model_id
                ),
            )
            return CompleteReducerResult(
                state=pruned,
                events=[
                    WakeWordDeleteModelEvent(engine=engine, model_id=model_id),
                ],
            )

        # --- intents / speech reporting ------------------------------------

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
