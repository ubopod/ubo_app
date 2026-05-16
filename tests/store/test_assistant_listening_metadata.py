"""Reducer + policy resolution tests for assistant listening metadata.

Class-identity discipline: integration tests earlier in the suite wipe
``sys.modules`` (see ``tests/fixtures/app.py``), so any module-level
``from ubo_app.store.services.assistant import …`` done at collection
time becomes stale by the time these tests run. The loader explicitly
``importlib.reload``s the store-side module and then ``exec_module``s
the reducer, so when the reducer's own imports resolve they see the
same freshly-loaded module objects. Tests pull every class from the
returned namespace — never from top-level imports.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    import pytest
    from redux import BaseAction


SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/090-assistant'


def _load_assistant(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Load the assistant reducer + namespace of its public classes."""
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())

    from ubo_app.store.services import assistant as assistant_module
    from ubo_app.store.services import keypad as keypad_module

    assistant_module = importlib.reload(assistant_module)
    keypad_module = importlib.reload(keypad_module)

    spec = importlib.util.spec_from_file_location(
        'assistant_service_reducer',
        SERVICE_PATH / 'reducer.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    return SimpleNamespace(
        reducer=module.reducer,
        # actions
        AssistantStartListeningAction=(
            assistant_module.AssistantStartListeningAction
        ),
        AssistantStopListeningAction=(
            assistant_module.AssistantStopListeningAction
        ),
        AssistantToggleListeningAction=(
            assistant_module.AssistantToggleListeningAction
        ),
        # state + policy types
        AssistantState=assistant_module.AssistantState,
        AssistantTriggerPolicy=assistant_module.AssistantTriggerPolicy,
        AssistantTriggerPolicyEntry=(
            assistant_module.AssistantTriggerPolicyEntry
        ),
        # matchers
        AnySourceMatcher=assistant_module.AnySourceMatcher,
        InfraredMatcher=assistant_module.InfraredMatcher,
        KeypadMatcher=assistant_module.KeypadMatcher,
        WakePhraseMatcher=assistant_module.WakePhraseMatcher,
        # trigger sources
        DesktopTriggerSource=assistant_module.DesktopTriggerSource,
        GrpcTriggerSource=assistant_module.GrpcTriggerSource,
        InfraredTriggerSource=assistant_module.InfraredTriggerSource,
        KeypadTriggerSource=assistant_module.KeypadTriggerSource,
        WakePhraseTriggerSource=assistant_module.WakePhraseTriggerSource,
        # stop reasons
        EndOfTurnPhraseStopReason=assistant_module.EndOfTurnPhraseStopReason,
        SilenceTimeoutStopReason=assistant_module.SilenceTimeoutStopReason,
        UserStopReason=assistant_module.UserStopReason,
        # policy resolution helper
        resolve_policy=assistant_module.resolve_policy,
        # keypad
        Key=keypad_module.Key,
    )


def _unwrap(ns: SimpleNamespace, result: object) -> Any:
    """Unwrap a reducer result that may be a CompleteReducerResult."""
    state = getattr(result, 'state', result)
    if isinstance(state, ns.AssistantState):
        return state
    return state


def _step(
    ns: SimpleNamespace,
    state: object,
    action: BaseAction,
) -> Any:
    return _unwrap(ns, ns.reducer(state, action))


def _init_state(ns: SimpleNamespace) -> Any:
    init_action_type = cast(
        'type[BaseAction]',
        ns.reducer.__globals__['InitAction'],
    )
    state = _step(ns, None, init_action_type())
    # Service unmutes during init for these reducer-level tests so listening
    # actions don't all early-exit on the mute notification path.
    return state(is_microphone_mute=False)


# ---------- resolve_policy ----------

def test_resolve_policy_returns_none_for_missing_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No source → no policy."""
    ns = _load_assistant(monkeypatch)
    state = ns.AssistantState()
    assert ns.resolve_policy(state.policies, None) is None


def test_resolve_policy_matches_wake_phrase_case_insensitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wake-phrase matcher is case-insensitive."""
    ns = _load_assistant(monkeypatch)
    policies = (
        ns.AssistantTriggerPolicyEntry(
            matcher=ns.WakePhraseMatcher(phrase="LET'S have a Conversation"),
            policy=ns.AssistantTriggerPolicy(
                end_of_turn_phrases=("i'm done",),
                requires_phrase_for_stop=True,
            ),
        ),
        ns.AssistantTriggerPolicyEntry(
            matcher=ns.AnySourceMatcher(),
            policy=ns.AssistantTriggerPolicy(),
        ),
    )
    source = ns.WakePhraseTriggerSource(phrase="let's have a conversation")
    policy = ns.resolve_policy(policies, source)

    assert policy is not None
    assert policy.requires_phrase_for_stop is True
    assert policy.end_of_turn_phrases == ("i'm done",)


def test_resolve_policy_walks_matchers_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First-match-wins: earlier entries override later ones."""
    ns = _load_assistant(monkeypatch)
    specific = ns.AssistantTriggerPolicy(silence_timeout_seconds=2.0)
    fallback = ns.AssistantTriggerPolicy(silence_timeout_seconds=10.0)
    policies = (
        ns.AssistantTriggerPolicyEntry(
            matcher=ns.KeypadMatcher(key=ns.Key.HOME),
            policy=specific,
        ),
        ns.AssistantTriggerPolicyEntry(matcher=ns.KeypadMatcher(), policy=fallback),
    )
    home = ns.KeypadTriggerSource(key=ns.Key.HOME)
    other = ns.KeypadTriggerSource(key=ns.Key.L1)

    assert ns.resolve_policy(policies, home) is specific
    assert ns.resolve_policy(policies, other) is fallback


def test_resolve_policy_falls_back_to_any_source_matcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sources with no specific matcher hit the AnySourceMatcher entry."""
    ns = _load_assistant(monkeypatch)
    fallback = ns.AssistantTriggerPolicy()
    policies = (
        ns.AssistantTriggerPolicyEntry(
            matcher=ns.WakePhraseMatcher(phrase='nope'),
            policy=ns.AssistantTriggerPolicy(silence_timeout_seconds=99),
        ),
        ns.AssistantTriggerPolicyEntry(matcher=ns.AnySourceMatcher(), policy=fallback),
    )
    assert ns.resolve_policy(policies, ns.GrpcTriggerSource()) is fallback
    assert ns.resolve_policy(policies, ns.DesktopTriggerSource()) is fallback


def test_resolve_policy_infrared_matcher_protocol_scancode_narrowing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Infrared matchers narrow by protocol/scancode when set."""
    ns = _load_assistant(monkeypatch)
    specific = ns.AssistantTriggerPolicy(silence_timeout_seconds=1.0)
    fallback = ns.AssistantTriggerPolicy(silence_timeout_seconds=5.0)
    policies = (
        ns.AssistantTriggerPolicyEntry(
            matcher=ns.InfraredMatcher(protocol='necx', scancode='0xbf04'),
            policy=specific,
        ),
        ns.AssistantTriggerPolicyEntry(matcher=ns.InfraredMatcher(), policy=fallback),
    )

    matched = ns.InfraredTriggerSource(protocol='necx', scancode='0xbf04')
    other = ns.InfraredTriggerSource(protocol='necx', scancode='0xff')

    assert ns.resolve_policy(policies, matched) is specific
    assert ns.resolve_policy(policies, other) is fallback


# ---------- start ----------

def test_start_writes_active_source_and_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Start populates is_listening, active_source, and active_policy."""
    ns = _load_assistant(monkeypatch)
    state = _init_state(ns)

    matcher = state.policies[0].matcher
    assert isinstance(matcher, ns.WakePhraseMatcher)
    source = ns.WakePhraseTriggerSource(phrase=matcher.phrase)
    next_state = _step(ns, state, ns.AssistantStartListeningAction(source=source))

    assert next_state.is_listening is True
    assert next_state.active_source == source
    assert next_state.active_policy is not None
    assert next_state.active_policy.requires_phrase_for_stop is True


def test_start_without_source_keeps_state_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy callers pass no source; listening=True, source/policy stay None."""
    ns = _load_assistant(monkeypatch)
    state = _init_state(ns)

    next_state = _step(ns, state, ns.AssistantStartListeningAction())
    assert next_state.is_listening is True
    assert next_state.active_source is None
    assert next_state.active_policy is None


def test_start_when_muted_does_not_record_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Muted-mic path: state.is_listening stays False, source not stored."""
    ns = _load_assistant(monkeypatch)
    init_action_type = cast(
        'type[BaseAction]',
        ns.reducer.__globals__['InitAction'],
    )
    state = _step(ns, None, init_action_type())
    assert state.is_microphone_mute is True

    source = ns.KeypadTriggerSource(key=ns.Key.HOME)
    next_state = _step(
        ns,
        state,
        ns.AssistantStartListeningAction(source=source),
    )
    assert next_state.is_listening is False
    assert next_state.active_source is None
    assert next_state.active_policy is None


# ---------- stop ----------

def test_stop_clears_active_session_and_records_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop clears active_source/policy and stores last_stop_reason."""
    ns = _load_assistant(monkeypatch)
    state = _init_state(ns)
    listening_state = _step(
        ns,
        state,
        ns.AssistantStartListeningAction(
            source=ns.KeypadTriggerSource(key=ns.Key.HOME),
        ),
    )
    assert listening_state.is_listening is True

    reason = ns.SilenceTimeoutStopReason(silence_seconds=2.0)
    next_state = _step(
        ns,
        listening_state,
        ns.AssistantStopListeningAction(reason=reason),
    )
    assert next_state.is_listening is False
    assert next_state.active_source is None
    assert next_state.active_policy is None
    assert next_state.last_stop_reason == reason


def test_stop_with_end_of_turn_reason_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-of-turn reason survives the round-trip into state."""
    ns = _load_assistant(monkeypatch)
    state = _init_state(ns)
    listening_state = _step(
        ns,
        state,
        ns.AssistantStartListeningAction(
            source=ns.WakePhraseTriggerSource(phrase='boot'),
        ),
    )
    reason = ns.EndOfTurnPhraseStopReason(
        phrase="i'm done",
        matched_text="okay i'm done",
    )
    next_state = _step(
        ns,
        listening_state,
        ns.AssistantStopListeningAction(reason=reason),
    )
    assert next_state.last_stop_reason == reason


# ---------- toggle ----------

def test_toggle_starts_with_source_when_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Toggle from idle → start with source captured."""
    ns = _load_assistant(monkeypatch)
    state = _init_state(ns)

    source = ns.InfraredTriggerSource(protocol='nec', scancode='0xa01b')
    next_state = _step(
        ns,
        state,
        ns.AssistantToggleListeningAction(source=source),
    )
    assert next_state.is_listening is True
    assert next_state.active_source == source


def test_toggle_stops_with_synthesised_user_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Toggle from listening → stop with UserStopReason(source=...)."""
    ns = _load_assistant(monkeypatch)
    state = _init_state(ns)
    source = ns.InfraredTriggerSource(protocol='nec', scancode='0xa01b')
    listening_state = _step(
        ns,
        state,
        ns.AssistantToggleListeningAction(source=source),
    )
    assert listening_state.is_listening is True

    next_state = _step(
        ns,
        listening_state,
        ns.AssistantToggleListeningAction(source=source),
    )
    assert next_state.is_listening is False
    assert next_state.last_stop_reason == ns.UserStopReason(source=source)
    assert next_state.active_source is None
    assert next_state.active_policy is None
