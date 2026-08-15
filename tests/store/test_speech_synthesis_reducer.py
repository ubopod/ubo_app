"""Reducer tests for the speech-synthesis forwarder service.

The service no longer owns a TTS engine — synthesis is forwarded to the
assistant's pipeline. Its reducer now only:

* flips ``is_screen_reader_enabled`` on ``SpeechSynthesisSetIsEnabledAction``,
  and
* always transforms ``SpeechSynthesisReadTextAction`` into a
  ``SpeechSynthesisSynthesizeTextEvent``.

The screen-reader toggle gates only the *automatic* notification readout, and
that gate lives in the notification menu handler — NOT in this reducer. So an
explicit/manual read request must still emit the synth event regardless of the
toggle, which the second test asserts.

Class-identity discipline mirrors ``test_notification_dismiss_stack.py``:
integration tests earlier in the suite wipe ``sys.modules``, so the reducer is
exec'd from file against a freshly-reloaded store-types module generation.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    from ubo_app.store.services.speech_synthesis import SpeechSynthesisState


SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/010-speech-synthesis'


def _load(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())

    from ubo_app.store.services import speech_synthesis as module

    module = importlib.reload(module)

    spec = importlib.util.spec_from_file_location(
        'speech_synthesis_service_reducer',
        SERVICE_PATH / 'reducer.py',
    )
    assert spec is not None
    assert spec.loader is not None
    reducer_module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = reducer_module
    spec.loader.exec_module(reducer_module)

    return SimpleNamespace(
        reducer=reducer_module.reducer,
        ReadableInformation=module.ReadableInformation,
        SpeechSynthesisReadTextAction=module.SpeechSynthesisReadTextAction,
        SpeechSynthesisSetIsEnabledAction=module.SpeechSynthesisSetIsEnabledAction,
        SpeechSynthesisSetPreferLocalAction=module.SpeechSynthesisSetPreferLocalAction,
        SpeechSynthesisSynthesizeTextEvent=module.SpeechSynthesisSynthesizeTextEvent,
        SpeechSynthesisState=module.SpeechSynthesisState,
    )


def _state(ns: SimpleNamespace, **kwargs: bool) -> SpeechSynthesisState:
    """Build state with both flags explicit, avoiding the real persistent store."""
    kwargs.setdefault('is_screen_reader_enabled', False)
    kwargs.setdefault('is_prefer_local_enabled', False)
    return cast('SpeechSynthesisState', ns.SpeechSynthesisState(**kwargs))


def test_set_is_enabled_flips_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """``SpeechSynthesisSetIsEnabledAction`` toggles the persisted flag."""
    ns = _load(monkeypatch)
    state = _state(ns, is_screen_reader_enabled=True)

    disabled = ns.reducer(state, ns.SpeechSynthesisSetIsEnabledAction(is_enabled=False))
    assert disabled.is_screen_reader_enabled is False

    enabled = ns.reducer(
        disabled,
        ns.SpeechSynthesisSetIsEnabledAction(is_enabled=True),
    )
    assert enabled.is_screen_reader_enabled is True


def test_set_prefer_local_flips_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """``SpeechSynthesisSetPreferLocalAction`` toggles only the prefer-local flag."""
    ns = _load(monkeypatch)
    state = _state(ns, is_screen_reader_enabled=True, is_prefer_local_enabled=False)

    enabled = ns.reducer(
        state,
        ns.SpeechSynthesisSetPreferLocalAction(is_enabled=True),
    )
    assert enabled.is_prefer_local_enabled is True
    # The screen-reader flag is untouched.
    assert enabled.is_screen_reader_enabled is True


def test_read_text_emits_event_even_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A read request always emits the synth event; the auto-read gate is elsewhere."""
    ns = _load(monkeypatch)
    state = _state(ns, is_screen_reader_enabled=False)

    result = ns.reducer(
        state,
        ns.SpeechSynthesisReadTextAction(
            information=ns.ReadableInformation(text='hello'),
        ),
    )

    assert result.state is state
    assert len(result.events) == 1
    event = result.events[0]
    assert isinstance(event, ns.SpeechSynthesisSynthesizeTextEvent)
    assert event.information.text == 'hello'


def test_init_action_builds_default_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """A None state plus InitAction yields a fresh default state."""
    from redux import InitAction

    ns = _load(monkeypatch)

    result = ns.reducer(None, InitAction())

    assert isinstance(result, ns.SpeechSynthesisState)


def test_none_state_without_init_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any non-init action against a None state is an initialization error."""
    from redux import InitializationActionError

    ns = _load(monkeypatch)

    with pytest.raises(InitializationActionError):
        ns.reducer(None, ns.SpeechSynthesisSetIsEnabledAction(is_enabled=True))


def test_unhandled_action_returns_state_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An action matching no case leaves the state untouched."""
    from redux import InitAction

    ns = _load(monkeypatch)
    state = _state(ns)

    assert ns.reducer(state, InitAction()) is state
