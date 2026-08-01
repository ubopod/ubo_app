"""Reducer tests for the multi-engine, per-trigger wake-word model.

The reducer maps a reported detection ``(engine, trigger_id)`` to the trigger's
mode and routes it through the shared ``_apply_wake_mode`` map: quick-chat /
conversation → ``AssistantStartListeningAction`` (carrying a
``WakePhraseTriggerSource``), the silence phrase → ``AssistantStopTalkingAction``,
and intents → ``INTENTS_WAITING``. ``SpeechRecognitionTriggerModeAction`` (used by
Infrared-bound remote keys) routes through the same map. The reducer also owns the
engine toggle + trigger add/remove handlers, the per-mode ``enabled_wake_modes``
switches, the OWW model lifecycle handlers, and the ``wake_slots`` →
``wake_engines`` migration.

Loads the service reducer via ``importlib.util.spec_from_file_location`` for the
same reason ``test_assistant_listening_metadata.py`` does — integration tests
earlier in the suite wipe ``sys.modules``.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from dataclasses import replace
from enum import StrEnum
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    import pytest
    from redux import BaseAction, CompleteReducerResult

    from ubo_app.store.services.speech_recognition import SpeechRecognitionState


SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/090-speech-recognition'


def _load(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Load the speech-recognition reducer + namespace of public classes."""
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())

    assistant_module = importlib.reload(
        importlib.import_module('ubo_app.store.services.assistant'),
    )
    sr = importlib.reload(
        importlib.import_module('ubo_app.store.services.speech_recognition'),
    )

    spec = importlib.util.spec_from_file_location(
        'speech_recognition_service_reducer',
        SERVICE_PATH / 'reducer.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    return SimpleNamespace(
        sr=sr,
        reducer=module.reducer,
        State=sr.SpeechRecognitionState,
        Status=sr.SpeechRecognitionStatus,
        WakeMode=sr.WakeMode,
        Engine=sr.WakeWordEngineName,
        Trigger=sr.WakeWordTrigger,
        EngineConfig=sr.WakeWordEngineConfig,
        engine_config=sr.engine_config,
        trigger_by_id=sr.trigger_by_id,
        ReportDetection=sr.SpeechRecognitionReportWakeWordDetectionAction,
        TriggerMode=sr.SpeechRecognitionTriggerModeAction,
        WakeEngineSetEnabledAction=sr.WakeEngineSetEnabledAction,
        WakeTriggerAddAction=sr.WakeTriggerAddAction,
        WakeTriggerRemoveAction=sr.WakeTriggerRemoveAction,
        SetAssistantEnabled=sr.SpeechRecognitionSetAssistantEnabledAction,
        SetWakeModeEnabled=sr.SpeechRecognitionSetWakeModeEnabledAction,
        WakeWordDeleteModelAction=sr.WakeWordDeleteModelAction,
        WakeWordDeleteModelEvent=sr.WakeWordDeleteModelEvent,
        WakeWordSetAvailableModelsAction=sr.WakeWordSetAvailableModelsAction,
        AssistantStartListeningAction=assistant_module.AssistantStartListeningAction,
        AssistantStopTalkingAction=assistant_module.AssistantStopTalkingAction,
        WakePhraseTriggerSource=assistant_module.WakePhraseTriggerSource,
        WyomingSatelliteWakeAction=importlib.import_module(
            'ubo_app.store.services.wyoming',
        ).WyomingSatelliteWakeAction,
    )


def _trigger(
    ns: SimpleNamespace,
    *,
    id: str,
    mode: object,
    value: str,
) -> object:
    """Build a WakeWordTrigger."""
    return ns.Trigger(id=id, label=value, mode=mode, value=value)


def _state(ns: SimpleNamespace, *configs: object) -> SpeechRecognitionState:
    """Build an init state with the given engine configs.

    Every wake mode is forced on so detection tests don't depend on the ambient
    persistent store (its default factory reads disk); the gate tests drop a mode
    explicitly via ``replace``.
    """
    init = cast(
        'type[BaseAction]',
        ns.reducer.__globals__['InitAction'],
    )
    base = cast('SpeechRecognitionState', ns.reducer(None, init()))
    return cast(
        'SpeechRecognitionState',
        replace(
            base,
            wake_engines=tuple(configs),
            enabled_wake_modes=tuple(ns.WakeMode),
        ),
    )


def _detect(
    ns: SimpleNamespace,
    state: SpeechRecognitionState,
    engine: object,
    trigger_id: str,
    phrase: str = '',
) -> CompleteReducerResult:
    """Run a wake-word detection report through the reducer."""
    return cast(
        'CompleteReducerResult',
        ns.reducer(
            state,
            ns.ReportDetection(
                engine_name=cast('Any', engine).value,
                trigger_id=trigger_id,
                phrase=phrase,
            ),
        ),
    )


def _starts(ns: SimpleNamespace, result: CompleteReducerResult) -> list:
    """Return the AssistantStartListeningAction actions in a reducer result."""
    return [
        a
        for a in cast('list[BaseAction]', result.actions or [])
        if isinstance(a, ns.AssistantStartListeningAction)
    ]


def _stops(ns: SimpleNamespace, result: CompleteReducerResult) -> list:
    """Return the AssistantStopTalkingAction actions in a reducer result."""
    return [
        a
        for a in cast('list[BaseAction]', result.actions or [])
        if isinstance(a, ns.AssistantStopTalkingAction)
    ]


def _wyoming_wakes(ns: SimpleNamespace, result: CompleteReducerResult) -> list:
    """Return the WyomingSatelliteWakeAction actions in a reducer result."""
    return [
        a
        for a in cast('list[BaseAction]', result.actions or [])
        if isinstance(a, ns.WyomingSatelliteWakeAction)
    ]


# ---------- detection -> mode routing ----------


def test_conversation_trigger_starts_listening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Conversation trigger → start listening with phrase/mode/detector."""
    ns = _load(monkeypatch)
    trig = _trigger(ns, id='c1', mode=ns.WakeMode.CONVERSATION, value='hey ubo')
    state = _state(
        ns,
        ns.EngineConfig(engine=ns.Engine.VOSK, enabled=True, triggers=(trig,)),
    )

    result = _detect(ns, state, ns.Engine.VOSK, 'c1', phrase='hey ubo')

    starts = _starts(ns, result)
    assert len(starts) == 1
    source = cast('Any', starts[0]).source
    assert isinstance(source, ns.WakePhraseTriggerSource)
    assert source.phrase == 'hey ubo'
    assert source.mode is ns.WakeMode.CONVERSATION
    assert source.detector == ns.Engine.VOSK.value


def test_openwakeword_trigger_also_fires_same_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A different engine independently fires the same (conversation) mode."""
    ns = _load(monkeypatch)
    trig = _trigger(
        ns,
        id='hey_jarvis',
        mode=ns.WakeMode.CONVERSATION,
        value='hey_jarvis',
    )
    state = _state(
        ns,
        ns.EngineConfig(engine=ns.Engine.VOSK, enabled=True, triggers=()),
        ns.EngineConfig(
            engine=ns.Engine.OPENWAKEWORD,
            enabled=True,
            triggers=(trig,),
        ),
    )

    result = _detect(ns, state, ns.Engine.OPENWAKEWORD, 'hey_jarvis')

    starts = _starts(ns, result)
    assert len(starts) == 1
    assert cast('Any', starts[0]).source.detector == ns.Engine.OPENWAKEWORD.value


def test_intents_trigger_enters_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    """Intents trigger → INTENTS_WAITING, no start action."""
    ns = _load(monkeypatch)
    trig = _trigger(ns, id='i1', mode=ns.WakeMode.INTENTS, value='ubo')
    state = _state(
        ns,
        ns.EngineConfig(engine=ns.Engine.VOSK, enabled=True, triggers=(trig,)),
    )

    result = _detect(ns, state, ns.Engine.VOSK, 'i1')

    assert result.state.status is ns.Status.INTENTS_WAITING
    assert not _starts(ns, result)


def test_stop_talking_trigger_dispatches_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop-talking (Silence) trigger → AssistantStopTalkingAction."""
    ns = _load(monkeypatch)
    trig = _trigger(ns, id='s1', mode=ns.WakeMode.STOP_TALKING, value='okay stop')
    state = _state(
        ns,
        ns.EngineConfig(engine=ns.Engine.VOSK, enabled=True, triggers=(trig,)),
    )

    result = _detect(ns, state, ns.Engine.VOSK, 's1', phrase='okay stop')

    stops = _stops(ns, result)
    assert len(stops) == 1
    assert cast('Any', stops[0]).phrase == 'okay stop'
    assert not _starts(ns, result)


def test_stop_talking_dismisses_the_command_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stop phrase during INTENTS_WAITING dismisses it — no 10s timeout wait.

    There is no assistant to silence here, so the stop is a plain dismissal: the
    listening indicator is cleared and no AssistantStopTalkingAction goes out.
    """
    ns = _load(monkeypatch)
    trig = _trigger(ns, id='s1', mode=ns.WakeMode.STOP_TALKING, value='okay enough')
    state = replace(
        _state(
            ns,
            ns.EngineConfig(engine=ns.Engine.VOSK, enabled=True, triggers=(trig,)),
        ),
        status=ns.Status.INTENTS_WAITING,
    )

    result = _detect(ns, state, ns.Engine.VOSK, 's1', phrase='okay enough')

    assert result.state.status is ns.Status.IDLE
    assert not _stops(ns, result)
    assert result.actions  # the RGB blank acknowledgment


def test_stop_talking_ends_an_armed_quick_chat_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stop phrase mid-quick-chat silences the assistant and disarms stage-1."""
    ns = _load(monkeypatch)
    trig = _trigger(ns, id='s1', mode=ns.WakeMode.STOP_TALKING, value='okay enough')
    state = replace(
        _state(
            ns,
            ns.EngineConfig(engine=ns.Engine.VOSK, enabled=True, triggers=(trig,)),
        ),
        status=ns.Status.ASSISTANT_WAITING,
    )

    result = _detect(ns, state, ns.Engine.VOSK, 's1', phrase='okay enough')

    assert result.state.status is ns.Status.IDLE
    assert len(_stops(ns, result)) == 1


def test_wake_detection_mid_session_does_not_disarm_stage_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stray wake while stage-1 is armed must leave ASSISTANT_WAITING intact.

    OpenWakeWord isn't grammar-constrained, so it can still fire during a
    quick-chat session. Dropping to IDLE here would disarm stage-1 for the rest
    of the session, and the arming autorun keys off the assistant's
    ``is_listening`` — unchanged — so it would never re-arm.
    """
    ns = _load(monkeypatch)
    trig = _trigger(ns, id='w1', mode=ns.WakeMode.QUICK_CHAT, value='hey_jarvis')
    state = replace(
        _state(
            ns,
            ns.EngineConfig(
                engine=ns.Engine.OPENWAKEWORD,
                enabled=True,
                triggers=(trig,),
            ),
        ),
        status=ns.Status.ASSISTANT_WAITING,
    )

    result = _detect(ns, state, ns.Engine.OPENWAKEWORD, 'w1', phrase='hey_jarvis')

    assert result.state.status is ns.Status.ASSISTANT_WAITING
    assert not _starts(ns, result)


def test_unknown_trigger_id_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unknown trigger id is a no-op."""
    ns = _load(monkeypatch)
    state = _state(
        ns,
        ns.EngineConfig(engine=ns.Engine.VOSK, enabled=True, triggers=()),
    )

    assert not _starts(ns, _detect(ns, state, ns.Engine.VOSK, 'nope'))


# ---------- direct mode trigger (Infrared-bound path) ----------


def test_trigger_mode_action_routes_each_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SpeechRecognitionTriggerModeAction shares the detection mode→effect map."""
    ns = _load(monkeypatch)
    state = _state(ns)

    conversation = ns.reducer(
        state,
        ns.TriggerMode(
            mode=ns.WakeMode.CONVERSATION,
            phrase='TV Power',
            detector='infrared',
        ),
    )
    starts = _starts(ns, conversation)
    assert len(starts) == 1
    assert cast('Any', starts[0]).source.detector == 'infrared'
    assert cast('Any', starts[0]).source.phrase == 'TV Power'

    stop = ns.reducer(state, ns.TriggerMode(mode=ns.WakeMode.STOP_TALKING))
    assert len(_stops(ns, stop)) == 1

    intents = ns.reducer(state, ns.TriggerMode(mode=ns.WakeMode.INTENTS))
    assert intents.state.status is ns.Status.INTENTS_WAITING


# ---------- per-mode enable gate ----------


def test_audio_detection_gated_by_wake_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disabled wake mode swallows an audio detection of that mode.

    The reducer enforces the per-mode ``enabled_wake_modes`` gate itself, not just
    the EnginesManager.
    """
    ns = _load(monkeypatch)
    trig = _trigger(ns, id='c1', mode=ns.WakeMode.CONVERSATION, value='hey ubo')
    state = replace(
        _state(
            ns,
            ns.EngineConfig(engine=ns.Engine.VOSK, enabled=True, triggers=(trig,)),
        ),
        enabled_wake_modes=(ns.WakeMode.INTENTS, ns.WakeMode.STOP_TALKING),
    )

    result = _detect(ns, state, ns.Engine.VOSK, 'c1', phrase='hey ubo')

    assert not _starts(ns, result)
    assert result.state.status is ns.Status.IDLE


def test_ir_trigger_mode_ignores_mode_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Infrared-bound mode trigger overrides an off mode switch.

    An explicit remote-key binding still starts the assistant when the mode is
    switched off (mirrors commands.py:_trigger_mode).
    """
    ns = _load(monkeypatch)
    state = replace(
        _state(ns),
        enabled_wake_modes=(ns.WakeMode.INTENTS, ns.WakeMode.STOP_TALKING),
    )

    result = ns.reducer(
        state,
        ns.TriggerMode(
            mode=ns.WakeMode.CONVERSATION,
            phrase='TV Power',
            detector='infrared',
        ),
    )

    assert len(_starts(ns, result)) == 1


# ---------- home assistant (wyoming) mode ----------


def test_home_assistant_trigger_hands_off_to_the_satellite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Home Assistant mode routes to Wyoming, not the on-device assistant."""
    ns = _load(monkeypatch)
    trig = _trigger(
        ns,
        id='ha1',
        mode=ns.WakeMode.HOME_ASSISTANT,
        value='hey home assistant',
    )
    state = _state(
        ns,
        ns.EngineConfig(engine=ns.Engine.VOSK, enabled=True, triggers=(trig,)),
    )

    result = _detect(ns, state, ns.Engine.VOSK, 'ha1', phrase='hey home assistant')

    wakes = _wyoming_wakes(ns, result)
    assert len(wakes) == 1
    assert cast('Any', wakes[0]).phrase == 'hey home assistant'
    assert cast('Any', wakes[0]).detector == ns.Engine.VOSK.value
    assert not _starts(ns, result)
    assert result.state.status is ns.Status.IDLE


def test_home_assistant_trigger_ignores_the_assistant_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Home Assistant is a separate destination, not a local assistant mode.

    Turning the on-device assistant off must not also silence the Home Assistant
    wake word.
    """
    ns = _load(monkeypatch)
    trig = _trigger(
        ns,
        id='ha1',
        mode=ns.WakeMode.HOME_ASSISTANT,
        value='hey home assistant',
    )
    state = replace(
        _state(
            ns,
            ns.EngineConfig(engine=ns.Engine.VOSK, enabled=True, triggers=(trig,)),
        ),
        assistant_enabled=False,
    )

    result = _detect(ns, state, ns.Engine.VOSK, 'ha1', phrase='hey home assistant')

    assert len(_wyoming_wakes(ns, result)) == 1


def test_home_assistant_trigger_leaves_an_armed_session_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Handing off to Home Assistant must not disarm local stage-1 matching."""
    ns = _load(monkeypatch)
    trig = _trigger(
        ns,
        id='ha1',
        mode=ns.WakeMode.HOME_ASSISTANT,
        value='hey home assistant',
    )
    state = replace(
        _state(
            ns,
            ns.EngineConfig(engine=ns.Engine.VOSK, enabled=True, triggers=(trig,)),
        ),
        status=ns.Status.ASSISTANT_WAITING,
    )

    result = _detect(ns, state, ns.Engine.VOSK, 'ha1', phrase='hey home assistant')

    assert len(_wyoming_wakes(ns, result)) == 1
    assert result.state.status is ns.Status.ASSISTANT_WAITING


def test_home_assistant_mode_is_matched_by_value_not_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mode that is equal-but-not-identical must still route to Wyoming.

    A trigger's mode can reach the reducer as a distinct enum object — rebuilt by
    the RPC layer or by a reloaded module — and an ``is`` check would silently
    drop the wake instead. Same trap that made ``connection_policy`` bind the
    wrong interface.
    """
    ns = _load(monkeypatch)

    class _ForeignWakeMode(StrEnum):
        HOME_ASSISTANT = 'home_assistant'

    trig = _trigger(
        ns,
        id='ha1',
        mode=_ForeignWakeMode.HOME_ASSISTANT,
        value='hey home assistant',
    )
    assert cast('Any', trig).mode is not ns.WakeMode.HOME_ASSISTANT
    assert cast('Any', trig).mode == ns.WakeMode.HOME_ASSISTANT
    state = _state(
        ns,
        ns.EngineConfig(engine=ns.Engine.VOSK, enabled=True, triggers=(trig,)),
    )

    result = _detect(ns, state, ns.Engine.VOSK, 'ha1', phrase='hey home assistant')

    assert len(_wyoming_wakes(ns, result)) == 1


def test_home_assistant_mode_is_seeded_on_a_fresh_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh install ships a Vosk phrase for the Home Assistant mode."""
    monkeypatch.setattr(
        'ubo_app.utils.persistent_store.read_from_persistent_store',
        lambda _key, **kwargs: kwargs.get('default'),
    )
    ns = _load(monkeypatch)
    init = cast('type[BaseAction]', ns.reducer.__globals__['InitAction'])
    state = cast('SpeechRecognitionState', ns.reducer(None, init()))

    vosk = ns.engine_config(state, ns.Engine.VOSK)
    assert vosk is not None
    modes = [trigger.mode for trigger in vosk.triggers]
    assert ns.WakeMode.HOME_ASSISTANT in modes


# ---------- engine / trigger config ----------


def test_set_engine_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """WakeEngineSetEnabledAction flips the engine enabled flag."""
    ns = _load(monkeypatch)
    state = _state(
        ns,
        ns.EngineConfig(engine=ns.Engine.OPENWAKEWORD, enabled=False, triggers=()),
    )

    new = ns.reducer(
        state,
        ns.WakeEngineSetEnabledAction(engine=ns.Engine.OPENWAKEWORD, enabled=True),
    )

    assert ns.engine_config(new, ns.Engine.OPENWAKEWORD).enabled is True


def test_trigger_add_remove(monkeypatch: pytest.MonkeyPatch) -> None:
    """Add/Remove mutate the engine triggers correctly (no per-trigger update)."""
    ns = _load(monkeypatch)
    state = _state(
        ns,
        ns.EngineConfig(engine=ns.Engine.VOSK, enabled=True, triggers=()),
    )

    state = ns.reducer(
        state,
        ns.WakeTriggerAddAction(
            engine=ns.Engine.VOSK,
            id='t1',
            label='hey ubo',
            mode=ns.WakeMode.CONVERSATION,
            value='hey ubo',
        ),
    )
    assert ns.trigger_by_id(state, ns.Engine.VOSK, 't1').value == 'hey ubo'

    state = ns.reducer(
        state,
        ns.WakeTriggerRemoveAction(engine=ns.Engine.VOSK, id='t1'),
    )
    assert ns.trigger_by_id(state, ns.Engine.VOSK, 't1') is None


def test_add_trigger_carries_sensitivity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WakeTriggerAddAction stores its sensitivity; omitting it defaults to 0.5."""
    ns = _load(monkeypatch)
    state = _state(
        ns,
        ns.EngineConfig(engine=ns.Engine.OPENWAKEWORD, enabled=True, triggers=()),
    )

    state = ns.reducer(
        state,
        ns.WakeTriggerAddAction(
            engine=ns.Engine.OPENWAKEWORD,
            id='t1',
            label='Hey Jarvis',
            mode=ns.WakeMode.CONVERSATION,
            value='hey_jarvis',
            sensitivity=0.8,
        ),
    )
    assert ns.trigger_by_id(state, ns.Engine.OPENWAKEWORD, 't1').sensitivity == 0.8

    state = ns.reducer(
        state,
        ns.WakeTriggerAddAction(
            engine=ns.Engine.OPENWAKEWORD,
            id='t2',
            label='Alexa',
            mode=ns.WakeMode.QUICK_CHAT,
            value='alexa',
        ),
    )
    assert ns.trigger_by_id(state, ns.Engine.OPENWAKEWORD, 't2').sensitivity == 0.5


def test_set_assistant_enabled_toggles_both_assistant_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SetAssistantEnabled adds/removes QUICK_CHAT + CONVERSATION together."""
    ns = _load(monkeypatch)
    state = _state(ns)

    off = ns.reducer(state, ns.SetAssistantEnabled(enabled=False))
    assert ns.WakeMode.QUICK_CHAT not in off.enabled_wake_modes
    assert ns.WakeMode.CONVERSATION not in off.enabled_wake_modes
    # INTENTS and STOP_TALKING are untouched.
    assert ns.WakeMode.INTENTS in off.enabled_wake_modes
    assert ns.WakeMode.STOP_TALKING in off.enabled_wake_modes

    on = ns.reducer(off, ns.SetAssistantEnabled(enabled=True))
    assert ns.WakeMode.QUICK_CHAT in on.enabled_wake_modes
    assert ns.WakeMode.CONVERSATION in on.enabled_wake_modes


def test_set_wake_mode_enabled_toggles_one_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SetWakeModeEnabled arms/disarms a single mode, in canonical order."""
    ns = _load(monkeypatch)
    state = _state(ns)

    off = ns.reducer(
        state,
        ns.SetWakeModeEnabled(mode=ns.WakeMode.CONVERSATION, enabled=False),
    )
    assert ns.WakeMode.CONVERSATION not in off.enabled_wake_modes
    # Others survive; order stays canonical (no CONVERSATION between QC and STOP).
    assert off.enabled_wake_modes == (
        ns.WakeMode.INTENTS,
        ns.WakeMode.QUICK_CHAT,
        ns.WakeMode.STOP_TALKING,
    )

    on = ns.reducer(
        off,
        ns.SetWakeModeEnabled(mode=ns.WakeMode.CONVERSATION, enabled=True),
    )
    assert on.enabled_wake_modes == tuple(ns.WakeMode)


def test_set_wake_mode_enabled_ignores_stop_talking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """STOP_TALKING has no switch — a stray toggle is a no-op."""
    ns = _load(monkeypatch)
    state = _state(ns)

    result = ns.reducer(
        state,
        ns.SetWakeModeEnabled(mode=ns.WakeMode.STOP_TALKING, enabled=False),
    )
    assert ns.WakeMode.STOP_TALKING in result.enabled_wake_modes


# ---------- OWW model lifecycle ----------


def test_delete_model_prunes_pool_trigger_and_emits_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deleting a model prunes pool + trigger and emits the delete event."""
    ns = _load(monkeypatch)
    trig = _trigger(ns, id='my_word', mode=ns.WakeMode.CONVERSATION, value='my_word')
    state = replace(
        _state(
            ns,
            ns.EngineConfig(
                engine=ns.Engine.OPENWAKEWORD,
                enabled=True,
                triggers=(trig,),
            ),
        ),
        openwakeword_models=('my_word', 'other'),
    )

    result = _detect_delete(ns, state)

    assert 'my_word' not in result.state.openwakeword_models
    assert 'other' in result.state.openwakeword_models
    assert ns.trigger_by_id(result.state, ns.Engine.OPENWAKEWORD, 'my_word') is None
    assert any(
        isinstance(event, ns.WakeWordDeleteModelEvent)
        for event in (result.events or [])
    )


def _detect_delete(
    ns: SimpleNamespace,
    state: SpeechRecognitionState,
) -> CompleteReducerResult:
    """Run a WakeWordDeleteModelAction for ``my_word`` through the reducer."""
    return cast(
        'CompleteReducerResult',
        ns.reducer(
            state,
            ns.WakeWordDeleteModelAction(
                engine=ns.Engine.OPENWAKEWORD,
                model_id='my_word',
            ),
        ),
    )


def test_delete_model_not_in_pool_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deleting an id absent from the pool (e.g. a shared helper) does nothing.

    A remote action must not be able to delete a model the device doesn't track:
    with no matching pool entry the reducer leaves state untouched and emits no
    delete event (so the off-reducer file delete never runs).
    """
    ns = _load(monkeypatch)
    state = replace(
        _state(
            ns,
            ns.EngineConfig(
                engine=ns.Engine.OPENWAKEWORD,
                enabled=True,
                triggers=(),
            ),
        ),
        openwakeword_models=('my_word',),
    )

    result = ns.reducer(
        state,
        ns.WakeWordDeleteModelAction(
            engine=ns.Engine.OPENWAKEWORD,
            model_id='embedding_model',
        ),
    )

    new_state = result.state if hasattr(result, 'state') else result
    assert new_state.openwakeword_models == ('my_word',)


def test_delete_model_wrong_engine_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A delete naming a non-OWW engine can't touch the OpenWakeWord pool.

    ``openwakeword_models`` is OWW-specific; a malformed/remote action with
    ``engine=VOSK`` (even with a valid OWW stem) must leave the pool and triggers
    untouched and emit no delete event.
    """
    ns = _load(monkeypatch)
    state = replace(
        _state(
            ns,
            ns.EngineConfig(
                engine=ns.Engine.OPENWAKEWORD,
                enabled=True,
                triggers=(),
            ),
        ),
        openwakeword_models=('my_word',),
    )

    result = ns.reducer(
        state,
        ns.WakeWordDeleteModelAction(engine=ns.Engine.VOSK, model_id='my_word'),
    )

    new_state = result.state if hasattr(result, 'state') else result
    assert new_state.openwakeword_models == ('my_word',)
    assert not getattr(result, 'events', None)


def test_add_trigger_clamps_out_of_range_sensitivity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sensitivity from an action is clamped to [0,1]; non-finite → 0.5 default."""
    ns = _load(monkeypatch)
    base = _state(
        ns,
        ns.EngineConfig(engine=ns.Engine.OPENWAKEWORD, enabled=True, triggers=()),
    )

    def _add(trigger_id: str, sensitivity: float) -> float:
        state = ns.reducer(
            base,
            ns.WakeTriggerAddAction(
                engine=ns.Engine.OPENWAKEWORD,
                id=trigger_id,
                label='Hey Jarvis',
                mode=ns.WakeMode.CONVERSATION,
                value='hey_jarvis',
                sensitivity=sensitivity,
            ),
        )
        return ns.trigger_by_id(state, ns.Engine.OPENWAKEWORD, trigger_id).sensitivity

    assert _add('hi', 5.0) == 1.0
    assert _add('lo', -2.0) == 0.0
    assert _add('nan', float('nan')) == 0.5


def test_set_available_models_replaces_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WakeWordSetAvailableModelsAction replaces the OWW pool."""
    ns = _load(monkeypatch)
    state = _state(
        ns,
        ns.EngineConfig(engine=ns.Engine.OPENWAKEWORD, enabled=True, triggers=()),
    )

    new = ns.reducer(
        state,
        ns.WakeWordSetAvailableModelsAction(
            engine=ns.Engine.OPENWAKEWORD,
            models=('a', 'b'),
        ),
    )

    assert new.openwakeword_models == ('a', 'b')


# ---------- migration ----------


def _patch_wake_slots(
    monkeypatch: pytest.MonkeyPatch,
    ns: SimpleNamespace,
    blob: str | None,
) -> None:
    """Make the persistent store return *blob* for wake_slots and None otherwise."""

    def _fake_read(key: str, **_: object) -> object:
        return blob if key == 'speech_recognition:wake_slots' else None

    monkeypatch.setattr(ns.sr, 'read_from_persistent_store', _fake_read)


def test_migration_only_enabled_slots(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only enabled slots migrate; a disabled mode maps to absence (not re-enabled)."""
    import json

    ns = _load(monkeypatch)
    blob = json.dumps(
        [
            {'mode': 'intents', 'phrases': ['ubo'], 'enabled': True},
            {'mode': 'quick_chat', 'phrases': ['hey ubo', 'yo ubo'], 'enabled': False},
            {'mode': 'conversation', 'phrases': ["let's chat"], 'enabled': False},
            {'mode': 'stop_talking', 'phrases': ['enough'], 'enabled': False},
        ],
    )
    _patch_wake_slots(monkeypatch, ns, blob)

    engines = ns.sr._load_wake_engines()  # noqa: SLF001
    by_name = {config.engine: config for config in engines}
    assert set(by_name) == {ns.Engine.VOSK, ns.Engine.OPENWAKEWORD}
    vosk = by_name[ns.Engine.VOSK]
    # Only the enabled INTENTS slot survives; every disabled slot is dropped.
    assert {trigger.value for trigger in vosk.triggers} == {'ubo'}
    assert by_name[ns.Engine.OPENWAKEWORD].triggers == ()
    assert not hasattr(vosk.triggers[0], 'enabled')


def test_migration_mixed_assistant_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quick Chat off + Conversation on → only Conversation migrates (not QC)."""
    import json

    ns = _load(monkeypatch)
    blob = json.dumps(
        [
            {'mode': 'intents', 'phrases': ['ubo'], 'enabled': True},
            {'mode': 'quick_chat', 'phrases': ['hey ubo'], 'enabled': False},
            {'mode': 'conversation', 'phrases': ["let's chat"], 'enabled': True},
            {'mode': 'stop_talking', 'phrases': ['enough'], 'enabled': False},
        ],
    )
    _patch_wake_slots(monkeypatch, ns, blob)

    vosk = next(
        config
        for config in ns.sr._load_wake_engines()  # noqa: SLF001
        if config.engine is ns.Engine.VOSK
    )
    values = {trigger.value for trigger in vosk.triggers}
    assert values == {'ubo', "let's chat"}  # disabled Quick Chat phrase dropped
    assert 'hey ubo' not in values


def test_migration_enabled_assistant_keeps_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enabled QC/CONV → assistant on; an enabled STOP slot keeps its phrase."""
    import json

    ns = _load(monkeypatch)
    blob = json.dumps(
        [
            {'mode': 'intents', 'phrases': ['ubo'], 'enabled': True},
            {'mode': 'quick_chat', 'phrases': ['hey ubo'], 'enabled': True},
            {'mode': 'conversation', 'phrases': ["let's chat"], 'enabled': True},
            {'mode': 'stop_talking', 'phrases': ['enough'], 'enabled': True},
        ],
    )
    _patch_wake_slots(monkeypatch, ns, blob)

    vosk = next(
        config
        for config in ns.sr._load_wake_engines()  # noqa: SLF001
        if config.engine is ns.Engine.VOSK
    )
    assert 'enough' in {trigger.value for trigger in vosk.triggers}


# ---------- enabled_wake_modes loader ----------


def _patch_persistent(
    monkeypatch: pytest.MonkeyPatch,
    ns: SimpleNamespace,
    values: dict[str, object],
) -> None:
    """Make the persistent store return *values* by key, None otherwise."""

    def _fake_read(key: str, **_: object) -> object:
        return values.get(key)

    monkeypatch.setattr(ns.sr, 'read_from_persistent_store', _fake_read)


def test_enabled_wake_modes_defaults_all_on_for_fresh_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No persisted key → every mode on."""
    ns = _load(monkeypatch)
    _patch_persistent(monkeypatch, ns, {})
    assert ns.sr._load_enabled_wake_modes() == tuple(ns.WakeMode)  # noqa: SLF001


def test_enabled_wake_modes_ignores_legacy_assistant_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A legacy assistant-off key is ignored — the device comes back all-on."""
    ns = _load(monkeypatch)
    _patch_persistent(
        monkeypatch,
        ns,
        {'speech_recognition:assistant_enabled': False},
    )
    assert ns.sr._load_enabled_wake_modes() == tuple(ns.WakeMode)  # noqa: SLF001


def test_enabled_wake_modes_round_trips_persisted_subset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A persisted subset loads back in canonical order; STOP always rides along."""
    ns = _load(monkeypatch)
    _patch_persistent(
        monkeypatch,
        ns,
        {'speech_recognition:enabled_wake_modes': ['intents', 'garbage']},
    )
    # Unknown values dropped; STOP_TALKING forced on even when absent.
    assert ns.sr._load_enabled_wake_modes() == (  # noqa: SLF001
        ns.WakeMode.INTENTS,
        ns.WakeMode.STOP_TALKING,
    )


# ---------- model download idempotency ----------


def _download_events(result: object) -> list:
    """Return any WakeWordDownloadModelsEvent in a reducer result."""
    events = getattr(result, 'events', None) or []
    return list(events)


def test_download_models_emits_event_when_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A first download dispatch marks DOWNLOADING and emits the download event."""
    ns = _load(monkeypatch)
    state = _state(ns)
    result = cast(
        'CompleteReducerResult',
        ns.reducer(
            state,
            ns.sr.WakeWordDownloadModelsAction(engine_name=ns.Engine.OPENWAKEWORD),
        ),
    )
    assert any(
        isinstance(event, ns.sr.WakeWordDownloadModelsEvent)
        for event in _download_events(result)
    )
    assert (
        ns.sr.model_status(result.state, ns.Engine.OPENWAKEWORD)
        is ns.sr.WakeWordModelStatus.DOWNLOADING
    )


def test_download_models_is_noop_while_downloading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A re-dispatch while DOWNLOADING emits no event (no overlapping loop)."""
    ns = _load(monkeypatch)
    downloading = replace(
        _state(ns),
        wake_word_models_status=ns.sr.set_model_status(
            (),
            ns.Engine.OPENWAKEWORD,
            ns.sr.WakeWordModelStatus.DOWNLOADING,
        ),
    )
    result = ns.reducer(
        downloading,
        ns.sr.WakeWordDownloadModelsAction(engine_name=ns.Engine.OPENWAKEWORD),
    )
    assert not any(
        isinstance(event, ns.sr.WakeWordDownloadModelsEvent)
        for event in _download_events(result)
    )
