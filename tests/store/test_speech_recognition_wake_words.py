"""Reducer tests for slot-driven wake-phrase handling in speech-recognition.

The reducer matches a detected word against any phrase of an *enabled* slot,
routes quick-chat/conversation to ``AssistantStartListeningAction`` (carrying a
``WakePhraseTriggerSource`` with the phrase, mode and detector) and the stop
phrase to ``AssistantStopTalkingAction`` (carrying phrase + detector). It also
enforces the Conversation⟺Stop enable coupling.

Loads the service reducer via ``importlib.util.spec_from_file_location`` for the
same reason ``test_assistant_listening_metadata.py`` does — integration tests
earlier in the suite wipe ``sys.modules``.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

from ubo_app.constants.assistant import (
    ASSISTANT_CONVERSATION_END_PHRASES,
    ASSISTANT_CONVERSATION_SILENCE_TIMEOUT_SECONDS,
    ASSISTANT_CONVERSATION_WAKE_WORD,
    ASSISTANT_DEFAULT_SILENCE_TIMEOUT_SECONDS,
    ASSISTANT_QUICK_CHAT_WAKE_PHRASE,
    ASSISTANT_STOP_TALKING_PHRASE,
    INTENTS_WAKE_WORD,
)

if TYPE_CHECKING:
    import pytest
    from redux import BaseAction, CompleteReducerResult

    from ubo_app.store.services.assistant import (
        AssistantStartListeningAction,
        WakePhraseTriggerSource,
    )
    from ubo_app.store.services.speech_recognition import SpeechRecognitionState


SERVICE_PATH = (
    Path(__file__).parents[2] / 'ubo_app/services/090-speech-recognition'
)

_DEFAULT_PHRASES = {
    'intents': (INTENTS_WAKE_WORD,),
    'quick_chat': (ASSISTANT_QUICK_CHAT_WAKE_PHRASE,),
    'conversation': (ASSISTANT_CONVERSATION_WAKE_WORD,),
    'stop_talking': (ASSISTANT_STOP_TALKING_PHRASE,),
}


def _load_speech_recognition(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Load the speech-recognition reducer + namespace of public classes."""
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())

    assistant_module = importlib.reload(
        importlib.import_module('ubo_app.store.services.assistant'),
    )
    speech_recognition_module = importlib.reload(
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

    sr = speech_recognition_module
    return SimpleNamespace(
        reducer=module.reducer,
        SpeechRecognitionState=sr.SpeechRecognitionState,
        SpeechRecognitionStatus=sr.SpeechRecognitionStatus,
        SpeechRecognitionReportWakeWordDetectionAction=(
            sr.SpeechRecognitionReportWakeWordDetectionAction
        ),
        SpeechRecognitionSetSlotEnabledAction=sr.SpeechRecognitionSetSlotEnabledAction,
        SpeechRecognitionSetWakePhrasesAction=sr.SpeechRecognitionSetWakePhrasesAction,
        SpeechRecognitionSetConversationEndPhrasesAction=(
            sr.SpeechRecognitionSetConversationEndPhrasesAction
        ),
        WakeMode=sr.WakeMode,
        WakeWordSlot=sr.WakeWordSlot,
        slot_for_mode=sr.slot_for_mode,
        AssistantStartListeningAction=assistant_module.AssistantStartListeningAction,
        AssistantStopTalkingAction=assistant_module.AssistantStopTalkingAction,
        WakePhraseTriggerSource=assistant_module.WakePhraseTriggerSource,
        resolve_policy=assistant_module.resolve_policy,
        _default_policies=assistant_module._default_policies,  # noqa: SLF001
    )


def _slots(ns: SimpleNamespace, *enabled: object) -> tuple[object, ...]:
    """Build the four slots with default phrases; *enabled* lists active modes."""
    order = (
        ns.WakeMode.INTENTS,
        ns.WakeMode.QUICK_CHAT,
        ns.WakeMode.CONVERSATION,
        ns.WakeMode.STOP_TALKING,
    )
    return tuple(
        ns.WakeWordSlot(
            mode=mode,
            phrases=_DEFAULT_PHRASES[mode.value],
            enabled=mode in enabled,
        )
        for mode in order
    )


def _init_state(ns: SimpleNamespace) -> SpeechRecognitionState:
    init_action_type = cast(
        'type[BaseAction]',
        ns.reducer.__globals__['InitAction'],
    )
    state = ns.reducer(None, init_action_type())
    return cast('SpeechRecognitionState', state)


def _state_with(ns: SimpleNamespace, *enabled: object) -> SpeechRecognitionState:
    return cast(
        'SpeechRecognitionState',
        replace(_init_state(ns), wake_slots=_slots(ns, *enabled)),
    )


def _step_wake_word(
    ns: SimpleNamespace,
    state: SpeechRecognitionState,
    wake_word: str,
    engine_name: str = 'Vosk',
) -> CompleteReducerResult:
    return cast(
        'CompleteReducerResult',
        ns.reducer(
            state,
            ns.SpeechRecognitionReportWakeWordDetectionAction(
                wake_word=wake_word,
                engine_name=engine_name,
            ),
        ),
    )


def _start_actions(ns: SimpleNamespace, result: CompleteReducerResult) -> list:
    return [
        a
        for a in cast('list[BaseAction]', result.actions)
        if isinstance(a, ns.AssistantStartListeningAction)
    ]


# ---------- wake-word routing ----------


def test_quick_chat_wake_phrase_dispatches_start_listening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quick-chat wake phrase → start listening with phrase, mode and detector."""
    ns = _load_speech_recognition(monkeypatch)
    state = _state_with(ns, ns.WakeMode.QUICK_CHAT)

    result = _step_wake_word(ns, state, ASSISTANT_QUICK_CHAT_WAKE_PHRASE)

    starts = _start_actions(ns, result)
    assert len(starts) == 1
    source = cast('AssistantStartListeningAction', starts[0]).source
    assert isinstance(source, ns.WakePhraseTriggerSource)
    typed = cast('WakePhraseTriggerSource', source)
    assert typed.phrase == ASSISTANT_QUICK_CHAT_WAKE_PHRASE
    assert typed.mode is ns.WakeMode.QUICK_CHAT
    assert typed.detector == 'Vosk'


def test_conversation_wake_phrase_dispatches_start_listening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Conversation wake phrase → start listening carrying the conversation mode."""
    ns = _load_speech_recognition(monkeypatch)
    state = _state_with(ns, ns.WakeMode.CONVERSATION)

    result = _step_wake_word(ns, state, ASSISTANT_CONVERSATION_WAKE_WORD)

    starts = _start_actions(ns, result)
    assert len(starts) == 1
    source = cast('WakePhraseTriggerSource', starts[0].source)
    assert source.phrase == ASSISTANT_CONVERSATION_WAKE_WORD
    assert source.mode is ns.WakeMode.CONVERSATION


def test_disabled_slot_does_not_trigger(monkeypatch: pytest.MonkeyPatch) -> None:
    """A phrase whose slot is disabled is ignored."""
    ns = _load_speech_recognition(monkeypatch)
    # Quick-chat NOT enabled.
    state = _state_with(ns, ns.WakeMode.CONVERSATION)

    result = _step_wake_word(ns, state, ASSISTANT_QUICK_CHAT_WAKE_PHRASE)

    assert not _start_actions(ns, result)


def test_unknown_wake_word_does_not_dispatch_start_listening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wake word that isn't any enabled phrase → no start action."""
    ns = _load_speech_recognition(monkeypatch)
    state = _state_with(ns, ns.WakeMode.QUICK_CHAT)

    result = _step_wake_word(ns, state, 'something else entirely')

    assert not _start_actions(ns, result)


def test_stop_talking_phrase_dispatches_stop_with_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop phrase → AssistantStopTalkingAction carrying phrase + detector."""
    ns = _load_speech_recognition(monkeypatch)
    state = _state_with(ns, ns.WakeMode.CONVERSATION, ns.WakeMode.STOP_TALKING)

    result = _step_wake_word(ns, state, ASSISTANT_STOP_TALKING_PHRASE)

    stops = [
        a
        for a in cast('list[BaseAction]', result.actions)
        if isinstance(a, ns.AssistantStopTalkingAction)
    ]
    assert len(stops) == 1
    stop = cast('Any', stops[0])
    assert stop.phrase == ASSISTANT_STOP_TALKING_PHRASE
    assert stop.detector == 'Vosk'
    assert not _start_actions(ns, result)


def test_multi_phrase_alternative_triggers(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-first alternative in a slot triggers the right mode."""
    ns = _load_speech_recognition(monkeypatch)
    base = _init_state(ns)
    slots = tuple(
        ns.WakeWordSlot(
            mode=slot.mode,
            phrases=('hey there', 'yo computer')
            if slot.mode is ns.WakeMode.QUICK_CHAT
            else slot.phrases,
            enabled=slot.mode is ns.WakeMode.QUICK_CHAT,
        )
        for slot in base.wake_slots
    )
    state = cast('SpeechRecognitionState', replace(base, wake_slots=slots))

    result = _step_wake_word(ns, state, 'yo computer')

    starts = _start_actions(ns, result)
    assert len(starts) == 1
    assert cast('WakePhraseTriggerSource', starts[0].source).mode is (
        ns.WakeMode.QUICK_CHAT
    )


# ---------- enable/disable coupling ----------


def test_disabling_conversation_also_disables_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Conversation and Stop toggle together."""
    ns = _load_speech_recognition(monkeypatch)
    state = _state_with(ns, ns.WakeMode.CONVERSATION, ns.WakeMode.STOP_TALKING)

    new_state = ns.reducer(
        state,
        ns.SpeechRecognitionSetSlotEnabledAction(
            mode=ns.WakeMode.CONVERSATION,
            enabled=False,
        ),
    )

    assert not ns.slot_for_mode(new_state, ns.WakeMode.CONVERSATION).enabled
    assert not ns.slot_for_mode(new_state, ns.WakeMode.STOP_TALKING).enabled


def test_enabling_stop_also_enables_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The coupling is symmetric: enabling Stop enables Conversation."""
    ns = _load_speech_recognition(monkeypatch)
    state = _state_with(ns)  # all disabled

    new_state = ns.reducer(
        state,
        ns.SpeechRecognitionSetSlotEnabledAction(
            mode=ns.WakeMode.STOP_TALKING,
            enabled=True,
        ),
    )

    assert ns.slot_for_mode(new_state, ns.WakeMode.STOP_TALKING).enabled
    assert ns.slot_for_mode(new_state, ns.WakeMode.CONVERSATION).enabled
    # Quick chat stays independent.
    assert not ns.slot_for_mode(new_state, ns.WakeMode.QUICK_CHAT).enabled


# ---------- editing phrases ----------


def test_set_wake_phrases_updates_the_right_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SpeechRecognitionSetWakePhrasesAction replaces a slot's phrases."""
    ns = _load_speech_recognition(monkeypatch)
    state = _state_with(ns, ns.WakeMode.QUICK_CHAT)

    new_state = ns.reducer(
        state,
        ns.SpeechRecognitionSetWakePhrasesAction(
            mode=ns.WakeMode.QUICK_CHAT,
            phrases=('hey there friend', 'yo computer'),
        ),
    )

    assert ns.slot_for_mode(new_state, ns.WakeMode.QUICK_CHAT).phrases == (
        'hey there friend',
        'yo computer',
    )
    # Other slots untouched.
    assert ns.slot_for_mode(new_state, ns.WakeMode.CONVERSATION).phrases == (
        ASSISTANT_CONVERSATION_WAKE_WORD,
    )


def test_set_conversation_end_phrases_updates_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SpeechRecognitionSetConversationEndPhrasesAction replaces the tuple."""
    ns = _load_speech_recognition(monkeypatch)
    state = _init_state(ns)

    new_state = ns.reducer(
        state,
        ns.SpeechRecognitionSetConversationEndPhrasesAction(
            phrases=('that is all', 'we are finished'),
        ),
    )

    assert new_state.conversation_end_phrases == ('that is all', 'we are finished')


def test_custom_phrase_triggers_after_edit(monkeypatch: pytest.MonkeyPatch) -> None:
    """An edited phrase triggers; the previous default no longer does."""
    ns = _load_speech_recognition(monkeypatch)
    base = _state_with(ns, ns.WakeMode.QUICK_CHAT)
    state = cast(
        'SpeechRecognitionState',
        ns.reducer(
            base,
            ns.SpeechRecognitionSetWakePhrasesAction(
                mode=ns.WakeMode.QUICK_CHAT,
                phrases=('talk to me now',),
            ),
        ),
    )

    assert _start_actions(ns, _step_wake_word(ns, state, 'talk to me now'))
    assert not _start_actions(
        ns,
        _step_wake_word(ns, state, ASSISTANT_QUICK_CHAT_WAKE_PHRASE),
    )


# ---------- default-policy resolution (assistant-side, mode-keyed) ----------


def test_default_policy_for_quick_chat_uses_silence_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quick-chat source → silence-timeout policy, no end phrases."""
    ns = _load_speech_recognition(monkeypatch)
    policies = ns._default_policies()  # noqa: SLF001
    source = ns.WakePhraseTriggerSource(
        phrase=ASSISTANT_QUICK_CHAT_WAKE_PHRASE,
        mode=ns.WakeMode.QUICK_CHAT,
    )

    policy = ns.resolve_policy(policies, source)

    assert policy is not None
    assert policy.silence_timeout_seconds == ASSISTANT_DEFAULT_SILENCE_TIMEOUT_SECONDS
    assert policy.end_of_turn_phrases == ()
    assert policy.completion_mode == 'silence'


def test_default_policy_for_conversation_uses_end_phrases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Conversation source → end-phrase policy with a long silence fallback."""
    ns = _load_speech_recognition(monkeypatch)
    policies = ns._default_policies()  # noqa: SLF001
    source = ns.WakePhraseTriggerSource(
        phrase=ASSISTANT_CONVERSATION_WAKE_WORD,
        mode=ns.WakeMode.CONVERSATION,
    )

    policy = ns.resolve_policy(policies, source)

    assert policy is not None
    assert policy.end_of_turn_phrases == ASSISTANT_CONVERSATION_END_PHRASES
    assert policy.completion_mode == 'silence'
    assert (
        policy.silence_timeout_seconds == ASSISTANT_CONVERSATION_SILENCE_TIMEOUT_SECONDS
    )
