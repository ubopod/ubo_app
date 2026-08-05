# ruff: noqa: D100, D103
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from commands import load_or_seed_commands
from pattern import PatternError, expand_pattern
from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
)

# The catalog is the authorization list for per-model downloads — see the
# ``WakeWordDownloadModelAction`` branch.
from ubo_app.engines.microwakeword_catalog import model_for as microwakeword_model_for
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
    SpeechRecognitionCommandDescriptor,
    SpeechRecognitionCommandsCatalog,
    SpeechRecognitionIntent,
    SpeechRecognitionRemoveCommandAction,
    SpeechRecognitionReportIntentDetectionAction,
    SpeechRecognitionReportIntentTimeoutAction,
    SpeechRecognitionReportSpeechAction,
    SpeechRecognitionReportWakeWordDetectionAction,
    SpeechRecognitionRunCommandAction,
    SpeechRecognitionSetAssistantEnabledAction,
    SpeechRecognitionSetAssistantListeningAction,
    SpeechRecognitionSetConversationEndPhrasesAction,
    SpeechRecognitionSetWakeModeEnabledAction,
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
    WakeWordDownloadModelAction,
    WakeWordDownloadModelEvent,
    WakeWordDownloadModelsAction,
    WakeWordDownloadModelsEvent,
    WakeWordEngineName,
    WakeWordModelStatus,
    WakeWordSetAvailableModelsAction,
    WakeWordSetModelsStatusAction,
    WakeWordTrigger,
    clamp_sensitivity,
    model_status,
    order_wake_modes,
    set_model_status,
    trigger_by_id,
)
from ubo_app.store.services.wyoming import WyomingSatelliteWakeAction

if TYPE_CHECKING:
    from collections.abc import Callable

    from redux import ReducerResult

    from ubo_app.store.main import UboAction


ACKNOWLEDGMENT_ACTION = RgbRingBlankAction()

_ASSISTANT_MODES = (WakeMode.QUICK_CHAT, WakeMode.CONVERSATION)

# Reported as the stop `detector` when stage-1 matching ends a quick-chat session.
QUICK_CHAT_COMMAND_DETECTOR = 'quick-chat-command'

# How many concrete phrases per command are handed to the LLM as examples. Enough
# to convey the shape of the command, few enough to keep the tool schema small.
_MAX_SAMPLE_PHRASES = 3


def _idle(state: SpeechRecognitionState) -> SpeechRecognitionState:
    """Return *state* at rest: nothing armed, no quick-chat session tracked."""
    return replace(
        state,
        status=SpeechRecognitionStatus.IDLE,
        assistant_session_audio_source='',
    )


def _command_descriptor(
    intent: SpeechRecognitionIntent,
) -> SpeechRecognitionCommandDescriptor:
    """Trim an intent to the id/label/examples the LLM tool schema needs.

    A malformed pattern falls back to its raw line, mirroring
    ``engines_manager._expand_phrases`` — one bad pattern must not take the whole
    catalog down with it.
    """
    samples: list[str] = []
    for phrase in intent.phrases:
        try:
            samples.extend(expand_pattern(phrase))
        except PatternError:
            samples.append(phrase)
        if len(samples) >= _MAX_SAMPLE_PHRASES:
            break
    return SpeechRecognitionCommandDescriptor(
        id=intent.id,
        label=intent.label,
        sample_phrases=samples[:_MAX_SAMPLE_PHRASES],
    )


def _with_commands_catalog(state: SpeechRecognitionState) -> SpeechRecognitionState:
    """Refresh the LLM-facing mirror of ``intents``.

    The catalog has to be materialised in state (rather than derived on read)
    because the assistant subprocess subscribes to it over gRPC by *field path*,
    not by selector.
    """
    return replace(
        state,
        commands_catalog=SpeechRecognitionCommandsCatalog(
            items=[_command_descriptor(intent) for intent in state.intents],
        ),
    )


def _model_pool(
    state: SpeechRecognitionState,
    engine: WakeWordEngineName,
) -> tuple[str, ...] | None:
    """Return *engine*'s on-disk model pool, or None if it doesn't have one.

    Vosk matches spoken phrases rather than per-wake-word model files, so it has
    no pool and nothing to delete.
    """
    if engine is WakeWordEngineName.OPENWAKEWORD:
        return state.openwakeword_models
    if engine is WakeWordEngineName.MICROWAKEWORD:
        return state.microwakeword_models
    return None


def _with_model_pool(
    state: SpeechRecognitionState,
    engine: WakeWordEngineName,
    models: tuple[str, ...],
) -> SpeechRecognitionState:
    """Return *state* with *engine*'s model pool replaced by *models*."""
    if engine is WakeWordEngineName.OPENWAKEWORD:
        return replace(state, openwakeword_models=models)
    if engine is WakeWordEngineName.MICROWAKEWORD:
        return replace(state, microwakeword_models=models)
    return state


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
    enforce_mode_gate: bool = True,
) -> CompleteReducerResult[
    SpeechRecognitionState,
    UboAction,
    SpeechRecognitionBoundActionTriggeredEvent
    | WakeWordDownloadModelsEvent
    | WakeWordDownloadModelEvent
    | WakeWordDeleteModelEvent,
]:
    """Map a triggered wake *mode* to its assistant effect.

    Shared by audio-stream detections (`SpeechRecognitionReportWakeWordDetection
    Action`) and Infrared-bound triggers (`SpeechRecognitionTriggerModeAction`):
    INTENTS arms the command listener (blue ring) when idle; QUICK_CHAT/
    CONVERSATION start the assistant when idle; STOP_TALKING stops it talking —
    or, while the command listener is armed, dismisses that window instead;
    HOME_ASSISTANT hands the utterance to the Wyoming satellite instead of the
    on-device assistant.

    ``enforce_mode_gate`` makes the per-mode ``enabled_wake_modes`` switches
    authoritative here in the (pure) reducer: the audio-detection path enforces
    them (a direct, e.g. remote-dispatched, detection of a disabled mode is
    swallowed), while the Infrared-bound path passes ``False`` so an explicit
    remote-key binding stays an intentional override (mirrors
    ``commands.py:_trigger_mode``). STOP_TALKING has no switch and is never gated.
    The EnginesManager's trigger-dropping for a disabled mode is then just an
    optimization, not the sole enforcement.
    """
    # Equality, not identity: a mode that has round-tripped through persistence
    # or the RPC layer compares equal to the canonical member without being it
    # (the same trap that made `connection_policy` bind the wrong interface).
    if mode == WakeMode.HOME_ASSISTANT:
        # A separate destination, not a local assistant mode: leave `status`
        # (and therefore any in-flight local session) untouched, and stay out of
        # the `assistant_enabled` gate below.
        return CompleteReducerResult(
            state=state,
            actions=[
                WyomingSatelliteWakeAction(phrase=phrase, detector=detector),
            ],
        )
    if (
        mode is not WakeMode.STOP_TALKING
        and enforce_mode_gate
        and mode not in state.enabled_wake_modes
    ):
        # This mode's switch is off — swallow the wake without acting on it.
        return CompleteReducerResult(state=_idle(state), actions=[])
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
        if state.status is SpeechRecognitionStatus.INTENTS_WAITING:
            # Dismiss the voice-shortcut window early — there is no assistant to
            # silence, the user just wants out of it without waiting for timeout.
            return CompleteReducerResult(
                state=_idle(state),
                actions=[ACKNOWLEDGMENT_ACTION],
            )
        return CompleteReducerResult(
            state=_idle(state),
            actions=[
                AssistantStopTalkingAction(phrase=phrase, detector=detector),
            ],
        )
    if state.status is SpeechRecognitionStatus.ASSISTANT_WAITING:
        # A wake detection mid-session. OpenWakeWord isn't grammar-constrained so
        # it can still fire here; dropping to IDLE would disarm stage-1 for the
        # rest of the session, and the arming autorun keys off the assistant's
        # `is_listening` — which hasn't changed — so it would never re-arm.
        return CompleteReducerResult(state=state, actions=[])
    return CompleteReducerResult(state=_idle(state), actions=[])


def reducer(
    state: SpeechRecognitionState | None,
    action: SpeechRecognitionAction,
) -> ReducerResult[
    SpeechRecognitionState,
    UboAction,
    SpeechRecognitionBoundActionTriggeredEvent
    | WakeWordDownloadModelsEvent
    | WakeWordDownloadModelEvent
    | WakeWordDeleteModelEvent,
]:
    if state is None:
        if isinstance(action, InitAction):
            intents, seeded_default_ids = load_or_seed_commands()
            return _with_commands_catalog(
                SpeechRecognitionState(
                    intents=intents,
                    seeded_default_ids=seeded_default_ids,
                ),
            )

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
            modes = set(state.enabled_wake_modes)
            if enabled:
                modes |= {WakeMode.QUICK_CHAT, WakeMode.CONVERSATION}
            else:
                modes -= {WakeMode.QUICK_CHAT, WakeMode.CONVERSATION}
            return replace(state, enabled_wake_modes=order_wake_modes(modes))

        case SpeechRecognitionSetWakeModeEnabledAction(mode=mode, enabled=enabled):
            if mode is WakeMode.STOP_TALKING:
                # Silence has no switch; ignore a stray toggle defensively.
                return state
            modes = set(state.enabled_wake_modes)
            if enabled:
                modes.add(mode)
            else:
                modes.discard(mode)
            return replace(state, enabled_wake_modes=order_wake_modes(modes))

        # --- voice commands (intents) --------------------------------------

        case SpeechRecognitionAddCommandAction():
            return _with_commands_catalog(
                replace(
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
                ),
            )

        case SpeechRecognitionUpdateCommandAction():
            return _with_commands_catalog(
                replace(
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
                ),
            )

        case SpeechRecognitionRemoveCommandAction():
            return _with_commands_catalog(
                replace(
                    state,
                    intents=[
                        intent for intent in state.intents if intent.id != action.id
                    ],
                ),
            )

        case SpeechRecognitionRunCommandAction(command_id=command_id):
            # Stage 2: the LLM matched an utterance stage-1 phrase matching missed.
            # Status-independent — by the time the tool call lands the quick-chat
            # session may already have ended.
            intent = next(
                (intent for intent in state.intents if intent.id == command_id),
                None,
            )
            if intent is None:
                return state
            return CompleteReducerResult(
                state=state,
                events=[
                    SpeechRecognitionBoundActionTriggeredEvent(
                        action_keys=intent.action_keys,
                        phrase=intent.label,
                    ),
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
            # when that mode's switch is off (see commands.py:_trigger_mode).
            return _apply_wake_mode(
                state,
                mode,
                phrase,
                detector,
                enforce_mode_gate=False,
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

        case WakeWordDownloadModelAction(engine=engine, model_id=model_id):
            # Only microWakeWord browses and fetches models one at a time; every
            # other engine downloads its whole default set via
            # ``WakeWordDownloadModelsAction``.
            if engine is not WakeWordEngineName.MICROWAKEWORD:
                return state
            # Authorize against the curated catalog: ``model_id`` reaches the
            # reducer from a menu tap *or* a remote gRPC dispatch, and it ends up
            # in a download URL and an on-disk filename. Only ids we ship are
            # accepted, so an arbitrary string can never become either.
            if microwakeword_model_for(model_id) is None:
                return state
            # Idempotent at the boundary, matching the batch action above: a
            # re-dispatch while a download is in flight must not emit a second
            # event and launch an overlapping fetch.
            if model_status(state, engine) is WakeWordModelStatus.DOWNLOADING:
                return state
            return CompleteReducerResult(
                state=replace(
                    state,
                    wake_word_models_status=set_model_status(
                        state.wake_word_models_status,
                        engine,
                        WakeWordModelStatus.DOWNLOADING,
                        model_id,
                    ),
                ),
                events=[
                    WakeWordDownloadModelEvent(engine=engine, model_id=model_id),
                ],
            )

        case WakeWordSetAvailableModelsAction(engine=engine, models=models):
            if engine is WakeWordEngineName.OPENWAKEWORD:
                return replace(state, openwakeword_models=models)
            if engine is WakeWordEngineName.MICROWAKEWORD:
                return replace(state, microwakeword_models=models)
            return state

        case WakeWordDeleteModelAction(engine=engine, model_id=model_id):
            # Only the model-pool engines have something deletable on disk. Guard
            # the engine so a malformed/remote action with the wrong engine can't
            # mutate a pool (or prune the wrong engine's triggers) while the
            # file-deleting event is dropped service-side.
            pool = _model_pool(state, engine)
            if pool is None:
                return state
            # Authorize against the known pool: a remote/client-dispatched action
            # must not delete an arbitrary id (e.g. a shared helper model). Only
            # ids present in the engine's pool are deletable.
            if model_id not in pool:
                return state
            # Drop the model from the pool + any trigger referencing it; delete
            # the file off-reducer via the event.
            remaining = tuple(stem for stem in pool if stem != model_id)
            pruned = _map_engine_triggers(
                _with_model_pool(state, engine, remaining),
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

        case SpeechRecognitionSetAssistantListeningAction(active=True):
            # Arm stage-1 alongside a quick-chat session. Only from rest: an armed
            # command window (INTENTS_WAITING) outranks it.
            if state.status is not SpeechRecognitionStatus.IDLE:
                return state
            return replace(
                state,
                status=SpeechRecognitionStatus.ASSISTANT_WAITING,
                assistant_session_audio_source=action.audio_source,
            )

        case SpeechRecognitionSetAssistantListeningAction(active=False):
            if state.status is not SpeechRecognitionStatus.ASSISTANT_WAITING:
                return state
            return _idle(state)

        case SpeechRecognitionReportIntentDetectionAction():
            # Stay pure: emit the event and let the service handler resolve the
            # action keys against the bindable-actions registry and dispatch
            # them (with the acknowledgment sequence).
            event = SpeechRecognitionBoundActionTriggeredEvent(
                action_keys=action.intent.action_keys,
                phrase=action.text,
            )
            if state.status is SpeechRecognitionStatus.INTENTS_WAITING:
                return CompleteReducerResult(state=_idle(state), events=[event])
            if state.status is SpeechRecognitionStatus.ASSISTANT_WAITING:
                # Stage 1: run the command and end the quick-chat session, so the
                # utterance is discarded instead of being answered by the LLM.
                return CompleteReducerResult(
                    state=_idle(state),
                    actions=[
                        AssistantStopTalkingAction(
                            phrase=action.text,
                            detector=QUICK_CHAT_COMMAND_DETECTOR,
                        ),
                    ],
                    events=[event],
                )
            # IDLE — a late or duplicate detection. Dropping it is what keeps the
            # command exactly-once.
            return state

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
