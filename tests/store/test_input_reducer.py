"""Reducer tests for the store-level input slice.

The input reducer is stateless (its state is always ``None``); it only turns
resolve/cancel actions into their matching events.
"""

from __future__ import annotations

from redux import CompleteReducerResult, InitAction

from ubo_app.store.input.reducer import reducer
from ubo_app.store.input.types import (
    InputCancelAction,
    InputCancelEvent,
    InputProvideAction,
    InputProvideEvent,
)


def test_provide_action_emits_provide_event() -> None:
    """``InputProvideAction`` forwards the id/value/result as a provide event."""
    result = reducer(None, InputProvideAction(id='q', value='yes', result=None))

    assert isinstance(result, CompleteReducerResult)
    assert len(result.events) == 1
    event = result.events[0]
    assert isinstance(event, InputProvideEvent)
    assert event.id == 'q'
    assert event.value == 'yes'


def test_cancel_action_emits_cancel_event() -> None:
    """``InputCancelAction`` forwards the id as a cancel event."""
    result = reducer(None, InputCancelAction(id='q'))

    assert isinstance(result, CompleteReducerResult)
    assert len(result.events) == 1
    assert isinstance(result.events[0], InputCancelEvent)
    assert result.events[0].id == 'q'


def test_unhandled_action_returns_none() -> None:
    """An action matching no case yields the (None) state unchanged."""
    assert reducer(None, InitAction()) is None
