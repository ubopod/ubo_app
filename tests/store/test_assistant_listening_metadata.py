"""Reducer + policy resolution tests for assistant listening metadata."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from ubo_app.store.services.assistant import (
    AnySourceMatcher,
    AssistantStartListeningAction,
    AssistantState,
    AssistantStopListeningAction,
    AssistantToggleListeningAction,
    AssistantTriggerPolicy,
    AssistantTriggerPolicyEntry,
    DesktopTriggerSource,
    EndOfTurnPhraseStopReason,
    GrpcTriggerSource,
    InfraredMatcher,
    InfraredTriggerSource,
    KeypadMatcher,
    KeypadTriggerSource,
    SilenceTimeoutStopReason,
    UserStopReason,
    WakePhraseMatcher,
    WakePhraseTriggerSource,
    resolve_policy,
)
from ubo_app.store.services.keypad import Key

if TYPE_CHECKING:
    import pytest
    from redux import BaseAction


SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/090-assistant'


class AssistantReducer(Protocol):
    """Protocol for the assistant reducer."""

    __globals__: dict[str, type[BaseAction]]

    def __call__(
        self,
        state: AssistantState | None,
        action: BaseAction,
    ) -> AssistantState:
        """Reduce an assistant state with one action."""
        ...


def _load_assistant_reducer(monkeypatch: pytest.MonkeyPatch) -> AssistantReducer:
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())
    spec = importlib.util.spec_from_file_location(
        'assistant_service_reducer',
        SERVICE_PATH / 'reducer.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast('AssistantReducer', module.reducer)


def _unwrap(result: object) -> AssistantState:
    """Unwrap a reducer result that may be a CompleteReducerResult."""
    state = getattr(result, 'state', result)
    return cast('AssistantState', state)


def _step(
    reducer: AssistantReducer,
    state: AssistantState | None,
    action: BaseAction,
) -> AssistantState:
    return _unwrap(reducer(state, action))


def _init_state(reducer: AssistantReducer) -> AssistantState:
    init_action_type = cast('type[BaseAction]', reducer.__globals__['InitAction'])
    state = _step(reducer, None, init_action_type())
    # Service unmutes during init for these reducer-level tests so listening
    # actions don't all early-exit on the mute notification path.
    return state(is_microphone_mute=False)


# ---------- resolve_policy ----------

def test_resolve_policy_returns_none_for_missing_source() -> None:
    """No source → no policy."""
    state = AssistantState()
    assert resolve_policy(state.policies, None) is None


def test_resolve_policy_matches_wake_phrase_case_insensitive() -> None:
    """Wake-phrase matcher is case-insensitive."""
    policies = (
        AssistantTriggerPolicyEntry(
            matcher=WakePhraseMatcher(phrase="LET'S have a Conversation"),
            policy=AssistantTriggerPolicy(
                end_of_turn_phrases=("i'm done",),
                requires_phrase_for_stop=True,
            ),
        ),
        AssistantTriggerPolicyEntry(
            matcher=AnySourceMatcher(),
            policy=AssistantTriggerPolicy(),
        ),
    )
    source = WakePhraseTriggerSource(phrase="let's have a conversation")
    policy = resolve_policy(policies, source)

    assert policy is not None
    assert policy.requires_phrase_for_stop is True
    assert policy.end_of_turn_phrases == ("i'm done",)


def test_resolve_policy_walks_matchers_in_order() -> None:
    """First-match-wins: earlier entries override later ones."""
    specific = AssistantTriggerPolicy(silence_timeout_seconds=2.0)
    fallback = AssistantTriggerPolicy(silence_timeout_seconds=10.0)
    policies = (
        AssistantTriggerPolicyEntry(
            matcher=KeypadMatcher(key=Key.HOME),
            policy=specific,
        ),
        AssistantTriggerPolicyEntry(matcher=KeypadMatcher(), policy=fallback),
    )
    home = KeypadTriggerSource(key=Key.HOME)
    other = KeypadTriggerSource(key=Key.L1)

    assert resolve_policy(policies, home) is specific
    assert resolve_policy(policies, other) is fallback


def test_resolve_policy_falls_back_to_any_source_matcher() -> None:
    """Sources with no specific matcher hit the AnySourceMatcher entry."""
    fallback = AssistantTriggerPolicy()
    policies = (
        AssistantTriggerPolicyEntry(
            matcher=WakePhraseMatcher(phrase='nope'),
            policy=AssistantTriggerPolicy(silence_timeout_seconds=99),
        ),
        AssistantTriggerPolicyEntry(matcher=AnySourceMatcher(), policy=fallback),
    )
    assert resolve_policy(policies, GrpcTriggerSource()) is fallback
    assert resolve_policy(policies, DesktopTriggerSource()) is fallback


def test_resolve_policy_infrared_matcher_protocol_scancode_narrowing() -> None:
    """Infrared matchers narrow by protocol/scancode when set."""
    specific = AssistantTriggerPolicy(silence_timeout_seconds=1.0)
    fallback = AssistantTriggerPolicy(silence_timeout_seconds=5.0)
    policies = (
        AssistantTriggerPolicyEntry(
            matcher=InfraredMatcher(protocol='necx', scancode='0xbf04'),
            policy=specific,
        ),
        AssistantTriggerPolicyEntry(matcher=InfraredMatcher(), policy=fallback),
    )

    matched = InfraredTriggerSource(protocol='necx', scancode='0xbf04')
    other = InfraredTriggerSource(protocol='necx', scancode='0xff')

    assert resolve_policy(policies, matched) is specific
    assert resolve_policy(policies, other) is fallback


# ---------- start ----------

def test_start_writes_active_source_and_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Start populates is_listening, active_source, and active_policy."""
    reducer = _load_assistant_reducer(monkeypatch)
    state = _init_state(reducer)

    matcher = state.policies[0].matcher
    assert isinstance(matcher, WakePhraseMatcher)
    source = WakePhraseTriggerSource(phrase=matcher.phrase)
    next_state = _step(reducer, state, AssistantStartListeningAction(source=source))

    assert next_state.is_listening is True
    assert next_state.active_source == source
    assert next_state.active_policy is not None
    assert next_state.active_policy.requires_phrase_for_stop is True


def test_start_without_source_keeps_state_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy callers pass no source; listening=True, source/policy stay None."""
    reducer = _load_assistant_reducer(monkeypatch)
    state = _init_state(reducer)

    next_state = _step(reducer, state, AssistantStartListeningAction())
    assert next_state.is_listening is True
    assert next_state.active_source is None
    assert next_state.active_policy is None


def test_start_when_muted_does_not_record_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Muted-mic path: state.is_listening stays False, source not stored."""
    reducer = _load_assistant_reducer(monkeypatch)
    init_action_type = cast('type[BaseAction]', reducer.__globals__['InitAction'])
    state = _step(reducer, None, init_action_type())
    assert state.is_microphone_mute is True

    source = KeypadTriggerSource(key=Key.HOME)
    next_state = _step(
        reducer,
        state,
        AssistantStartListeningAction(source=source),
    )
    assert next_state.is_listening is False
    assert next_state.active_source is None
    assert next_state.active_policy is None


# ---------- stop ----------

def test_stop_clears_active_session_and_records_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop clears active_source/policy and stores last_stop_reason."""
    reducer = _load_assistant_reducer(monkeypatch)
    state = _init_state(reducer)
    listening_state = _step(
        reducer,
        state,
        AssistantStartListeningAction(source=KeypadTriggerSource(key=Key.HOME)),
    )
    assert listening_state.is_listening is True

    reason = SilenceTimeoutStopReason(silence_seconds=2.0)
    next_state = _step(
        reducer,
        listening_state,
        AssistantStopListeningAction(reason=reason),
    )
    assert next_state.is_listening is False
    assert next_state.active_source is None
    assert next_state.active_policy is None
    assert next_state.last_stop_reason == reason


def test_stop_with_end_of_turn_reason_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-of-turn reason survives the round-trip into state."""
    reducer = _load_assistant_reducer(monkeypatch)
    state = _init_state(reducer)
    listening_state = _step(
        reducer,
        state,
        AssistantStartListeningAction(
            source=WakePhraseTriggerSource(phrase='boot'),
        ),
    )
    reason = EndOfTurnPhraseStopReason(
        phrase="i'm done",
        matched_text="okay i'm done",
    )
    next_state = _step(
        reducer,
        listening_state,
        AssistantStopListeningAction(reason=reason),
    )
    assert next_state.last_stop_reason == reason


# ---------- toggle ----------

def test_toggle_starts_with_source_when_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Toggle from idle → start with source captured."""
    reducer = _load_assistant_reducer(monkeypatch)
    state = _init_state(reducer)

    source = InfraredTriggerSource(protocol='nec', scancode='0xa01b')
    next_state = _step(
        reducer,
        state,
        AssistantToggleListeningAction(source=source),
    )
    assert next_state.is_listening is True
    assert next_state.active_source == source


def test_toggle_stops_with_synthesised_user_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Toggle from listening → stop with UserStopReason(source=...)."""
    reducer = _load_assistant_reducer(monkeypatch)
    state = _init_state(reducer)
    source = InfraredTriggerSource(protocol='nec', scancode='0xa01b')
    listening_state = _step(
        reducer,
        state,
        AssistantToggleListeningAction(source=source),
    )
    assert listening_state.is_listening is True

    next_state = _step(
        reducer,
        listening_state,
        AssistantToggleListeningAction(source=source),
    )
    assert next_state.is_listening is False
    assert next_state.last_stop_reason == UserStopReason(source=source)
    assert next_state.active_source is None
    assert next_state.active_policy is None
