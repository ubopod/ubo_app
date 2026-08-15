"""Reducer tests for the status-icons store slice.

The reducer keeps the status-bar icon list sorted by priority, de-duplicates
by id on re-registration, and drops a service's icons when that service goes
inactive.
"""

from __future__ import annotations

import pytest
from redux import InitAction, InitializationActionError

from ubo_app.store.settings.types import SettingsServiceSetStatusAction
from ubo_app.store.status_icons.reducer import reducer
from ubo_app.store.status_icons.types import (
    StatusIconsRegisterAction,
    StatusIconsState,
)


def _state() -> StatusIconsState:
    state = reducer(None, InitAction())
    assert isinstance(state, StatusIconsState)
    return state


def test_none_state_without_init_raises() -> None:
    """A non-init action against a None state is an initialization error."""
    with pytest.raises(InitializationActionError):
        reducer(None, StatusIconsRegisterAction(icon='x', service='svc'))


def test_register_adds_icons_sorted_by_priority() -> None:
    """Registered icons are ordered by ascending priority."""
    state = _state()
    state = reducer(
        state,
        StatusIconsRegisterAction(icon='b', priority=5, id='b', service='svc'),
    )
    state = reducer(
        state,
        StatusIconsRegisterAction(icon='a', priority=1, id='a', service='svc'),
    )

    assert [icon.symbol for icon in state.icons] == ['a', 'b']


def test_register_same_id_replaces_instead_of_duplicating() -> None:
    """Re-registering the same id updates that icon rather than adding another."""
    state = _state()
    state = reducer(
        state,
        StatusIconsRegisterAction(icon='old', id='k', service='svc'),
    )
    state = reducer(
        state,
        StatusIconsRegisterAction(icon='new', id='k', service='svc'),
    )

    matching = [icon for icon in state.icons if icon.id == 'k']
    assert len(matching) == 1
    assert matching[0].symbol == 'new'


def test_service_going_inactive_removes_its_icons() -> None:
    """Marking a service inactive drops only that service's icons."""
    state = _state()
    state = reducer(
        state,
        StatusIconsRegisterAction(icon='a', id='a', service='svc-1'),
    )
    state = reducer(
        state,
        StatusIconsRegisterAction(icon='b', id='b', service='svc-2'),
    )

    state = reducer(
        state,
        SettingsServiceSetStatusAction(service_id='svc-1', is_active=False),
    )

    assert [icon.service_id for icon in state.icons] == ['svc-2']


def test_unhandled_action_returns_state_unchanged() -> None:
    """An action matching no case leaves the state untouched."""
    state = _state()
    assert reducer(state, InitAction()) is state
