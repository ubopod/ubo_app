"""Reducer tests for assistant wake-phrase handling in speech-recognition.

The reducer must route both ``ASSISTANT_QUICK_CHAT_WAKE_PHRASE`` and
``ASSISTANT_CONVERSATION_WAKE_WORD`` to ``AssistantStartListeningAction`` and
must pass the matched phrase as a ``WakePhraseTriggerSource`` so the
assistant-side policy resolver can pick the correct policy.

Loads the service reducer via ``importlib.util.spec_from_file_location`` for
the same reason ``test_assistant_listening_metadata.py`` does — integration
tests earlier in the suite wipe ``sys.modules``.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from ubo_app.constants.assistant import (
    ASSISTANT_CONVERSATION_END_PHRASES,
    ASSISTANT_CONVERSATION_SILENCE_TIMEOUT_SECONDS,
    ASSISTANT_CONVERSATION_WAKE_WORD,
    ASSISTANT_DEFAULT_SILENCE_TIMEOUT_SECONDS,
    ASSISTANT_QUICK_CHAT_WAKE_PHRASE,
    ASSISTANT_STOP_TALKING_PHRASE,
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


def _load_speech_recognition(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Load the speech-recognition reducer + namespace of public classes."""
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())

    # Reload the *current* ``sys.modules`` entries rather than references bound
    # via ``from ... import``: an earlier integration test in the session can
    # leave the package attribute and its ``sys.modules`` entry pointing at
    # different module objects, which makes ``importlib.reload`` of the stale
    # reference raise ``ImportError: module ... not in sys.modules``.
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

    return SimpleNamespace(
        reducer=module.reducer,
        # speech-recognition types
        SpeechRecognitionState=speech_recognition_module.SpeechRecognitionState,
        SpeechRecognitionStatus=speech_recognition_module.SpeechRecognitionStatus,
        SpeechRecognitionReportWakeWordDetectionAction=(
            speech_recognition_module.SpeechRecognitionReportWakeWordDetectionAction
        ),
        # assistant actions + trigger source the reducer dispatches
        AssistantStartListeningAction=(
            assistant_module.AssistantStartListeningAction
        ),
        AssistantStopTalkingAction=(
            assistant_module.AssistantStopTalkingAction
        ),
        WakePhraseTriggerSource=assistant_module.WakePhraseTriggerSource,
        # policy resolution helper + factory for default-policy tests
        resolve_policy=assistant_module.resolve_policy,
        _default_policies=assistant_module._default_policies,  # noqa: SLF001
    )


def _init_state(ns: SimpleNamespace) -> SpeechRecognitionState:
    init_action_type = cast(
        'type[BaseAction]',
        ns.reducer.__globals__['InitAction'],
    )
    state = ns.reducer(None, init_action_type())
    return cast('SpeechRecognitionState', state)


def _step_wake_word(
    ns: SimpleNamespace,
    state: SpeechRecognitionState,
    wake_word: str,
) -> CompleteReducerResult:
    return cast(
        'CompleteReducerResult',
        ns.reducer(
            state,
            ns.SpeechRecognitionReportWakeWordDetectionAction(wake_word=wake_word),
        ),
    )


# ---------- wake-word routing ----------


def test_quick_chat_wake_phrase_dispatches_start_listening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quick-chat wake phrase → AssistantStartListeningAction with that phrase."""
    ns = _load_speech_recognition(monkeypatch)
    state = _init_state(ns)
    assert state.status is ns.SpeechRecognitionStatus.IDLE

    result = _step_wake_word(ns, state, ASSISTANT_QUICK_CHAT_WAKE_PHRASE)

    actions = cast('list[BaseAction]', result.actions)
    start_actions = [
        a for a in actions if isinstance(a, ns.AssistantStartListeningAction)
    ]
    assert len(start_actions) == 1
    source = cast('AssistantStartListeningAction', start_actions[0]).source
    assert isinstance(source, ns.WakePhraseTriggerSource)
    assert (
        cast('WakePhraseTriggerSource', source).phrase
        == ASSISTANT_QUICK_CHAT_WAKE_PHRASE
    )


def test_conversation_wake_phrase_dispatches_start_listening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Conversation wake phrase → AssistantStartListeningAction with that phrase."""
    ns = _load_speech_recognition(monkeypatch)
    state = _init_state(ns)
    assert state.status is ns.SpeechRecognitionStatus.IDLE

    result = _step_wake_word(ns, state, ASSISTANT_CONVERSATION_WAKE_WORD)

    actions = cast('list[BaseAction]', result.actions)
    start_actions = [
        a for a in actions if isinstance(a, ns.AssistantStartListeningAction)
    ]
    assert len(start_actions) == 1
    source = cast('AssistantStartListeningAction', start_actions[0]).source
    assert isinstance(source, ns.WakePhraseTriggerSource)
    assert (
        cast('WakePhraseTriggerSource', source).phrase
        == ASSISTANT_CONVERSATION_WAKE_WORD
    )


def test_unknown_wake_word_does_not_dispatch_start_listening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wake word that isn't any registered phrase → no start action."""
    ns = _load_speech_recognition(monkeypatch)
    state = _init_state(ns)

    result = _step_wake_word(ns, state, 'something else entirely')

    actions = cast('list[BaseAction]', result.actions)
    assert not any(
        isinstance(a, ns.AssistantStartListeningAction) for a in actions
    )


def test_stop_talking_phrase_dispatches_stop_talking_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop-talking phrase → AssistantStopTalkingAction, no start listening."""
    ns = _load_speech_recognition(monkeypatch)
    state = _init_state(ns)

    result = _step_wake_word(ns, state, ASSISTANT_STOP_TALKING_PHRASE)

    actions = cast('list[BaseAction]', result.actions)
    stop_actions = [
        a for a in actions if isinstance(a, ns.AssistantStopTalkingAction)
    ]
    assert len(stop_actions) == 1
    assert not any(
        isinstance(a, ns.AssistantStartListeningAction) for a in actions
    )


# ---------- default-policy resolution ----------


def test_default_policy_for_quick_chat_uses_silence_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quick-chat source → silence-timeout policy, no end phrases."""
    ns = _load_speech_recognition(monkeypatch)
    policies = ns._default_policies()  # noqa: SLF001
    source = ns.WakePhraseTriggerSource(phrase=ASSISTANT_QUICK_CHAT_WAKE_PHRASE)

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
    source = ns.WakePhraseTriggerSource(phrase=ASSISTANT_CONVERSATION_WAKE_WORD)

    policy = ns.resolve_policy(policies, source)

    assert policy is not None
    assert policy.end_of_turn_phrases == ASSISTANT_CONVERSATION_END_PHRASES
    assert policy.completion_mode == 'silence'
    assert (
        policy.silence_timeout_seconds == ASSISTANT_CONVERSATION_SILENCE_TIMEOUT_SECONDS
    )
