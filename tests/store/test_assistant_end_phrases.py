"""Reducer test: editing conversation end phrases updates table + active policy.

``AssistantSetConversationEndPhrasesAction`` must rewrite the conversation
entry in ``AssistantState.policies`` and — when the conversation source is the
currently active one — also ``active_policy`` (the field the subprocess
watches), so a mid-conversation edit takes effect immediately.

Follows the class-identity discipline of ``test_assistant_listening_metadata``:
reload the store modules and ``exec_module`` the reducer so every class comes
from the same freshly-loaded generation.
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

    from ubo_app.store.services.assistant import AssistantState

SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/090-assistant'


def _load(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())

    # Reload speech_recognition FIRST so the assistant module's
    # ``from ...speech_recognition import WakeMode`` (used by ``_default_policies``)
    # binds to the same freshly-loaded enum class that ``ns.WakeMode`` exposes —
    # otherwise ``is``/``==`` comparisons cross module generations and fail.
    speech_recognition_module = importlib.reload(
        importlib.import_module('ubo_app.store.services.speech_recognition'),
    )
    assistant_module = importlib.reload(
        importlib.import_module('ubo_app.store.services.assistant'),
    )
    importlib.reload(importlib.import_module('ubo_app.store.services.keypad'))

    spec = importlib.util.spec_from_file_location(
        'assistant_service_reducer_end_phrases',
        SERVICE_PATH / 'reducer.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    return SimpleNamespace(
        reducer=module.reducer,
        AssistantState=assistant_module.AssistantState,
        WakePhraseMatcher=assistant_module.WakePhraseMatcher,
        WakePhraseTriggerSource=assistant_module.WakePhraseTriggerSource,
        AssistantSetConversationEndPhrasesAction=(
            assistant_module.AssistantSetConversationEndPhrasesAction
        ),
        WakeMode=speech_recognition_module.WakeMode,
    )


def _conversation_policy(ns: SimpleNamespace, state: AssistantState) -> Any:  # noqa: ANN401
    """Return the policy whose matcher targets the conversation mode."""
    for entry in state.policies:
        if getattr(entry.matcher, 'mode', None) is ns.WakeMode.CONVERSATION:
            return entry.policy
    msg = 'No conversation policy entry found'
    raise AssertionError(msg)


def test_updates_policy_table(monkeypatch: pytest.MonkeyPatch) -> None:
    """The conversation entry in the table gets the new end phrases."""
    ns = _load(monkeypatch)
    state = ns.AssistantState()

    new_state = cast(
        'AssistantState',
        ns.reducer(
            state,
            ns.AssistantSetConversationEndPhrasesAction(phrases=('that is all',)),
        ),
    )

    policy = _conversation_policy(ns, new_state)
    assert policy.end_of_turn_phrases == ('that is all',)


def test_updates_active_policy_when_conversation_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When conversation is the active source, active_policy updates too."""
    ns = _load(monkeypatch)
    base = ns.AssistantState()
    state = base(
        active_source=ns.WakePhraseTriggerSource(
            phrase="let's have a conversation",
            mode=ns.WakeMode.CONVERSATION,
        ),
        active_policy=_conversation_policy(ns, base),
    )

    new_state = cast(
        'AssistantState',
        ns.reducer(
            state,
            ns.AssistantSetConversationEndPhrasesAction(phrases=('we are finished',)),
        ),
    )

    assert new_state.active_policy is not None
    assert new_state.active_policy.end_of_turn_phrases == ('we are finished',)


def test_active_policy_untouched_when_other_source_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-conversation active source leaves active_policy unchanged."""
    ns = _load(monkeypatch)
    base = ns.AssistantState()
    quick_chat_source = ns.WakePhraseTriggerSource(
        phrase='hey quick question',
        mode=ns.WakeMode.QUICK_CHAT,
    )
    state = base(active_source=quick_chat_source, active_policy=None)

    new_state = cast(
        'AssistantState',
        ns.reducer(
            state,
            ns.AssistantSetConversationEndPhrasesAction(phrases=('done now',)),
        ),
    )

    # Active policy stays None; only the table changed.
    assert new_state.active_policy is None
    assert _conversation_policy(ns, new_state).end_of_turn_phrases == ('done now',)
