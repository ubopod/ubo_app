"""Tests for restyling an already-registered app.

Registration raises on a duplicate key, so an app whose appearance tracks live
state has no way to say so without this action.
"""

from __future__ import annotations

from redux import InitAction

from ubo_app.store.core.reducer import reducer
from ubo_app.store.core.types import (
    MainState,
    RegisterRegularAppAction,
    UpdateRegisteredAppAction,
)


def _state_with_app() -> MainState:
    state = reducer(None, InitAction())
    assert isinstance(state, MainState)
    return reducer(
        state,
        RegisterRegularAppAction(
            label='Portainer',
            icon='󰡨',
            action_id='docker:open:portainer',
            service='docker',
            key='portainer',
        ),
    )


def test_update_tints_without_touching_identity() -> None:
    """Only presentation moves; the label and action stay put."""
    state = _state_with_app()

    result = reducer(
        state,
        UpdateRegisteredAppAction(
            service='docker',
            key='portainer',
            color='#FF3F51',
        ),
    )

    entry = result.registered_apps['docker:portainer']
    assert entry.color == '#FF3F51'
    assert entry.label == 'Portainer'
    assert entry.icon == '󰡨'
    assert entry.action_id == 'docker:open:portainer'


def test_omitted_fields_are_left_alone() -> None:
    """A colour-only update must not blank the icon."""
    state = _state_with_app()

    result = reducer(
        state,
        UpdateRegisteredAppAction(service='docker', key='portainer', color='#008000'),
    )

    assert result.registered_apps['docker:portainer'].icon == '󰡨'
    assert result.registered_apps['docker:portainer'].background_color is None


def test_unknown_key_is_a_no_op() -> None:
    """The Docker autorun can fire while an app is being removed."""
    state = _state_with_app()

    result = reducer(
        state,
        UpdateRegisteredAppAction(service='docker', key='gone', color='#FF3F51'),
    )

    assert result is state


def test_identical_update_returns_the_same_state() -> None:
    """Re-rendering the menu must not churn state for every connected client."""
    state = _state_with_app()
    tinted = reducer(
        state,
        UpdateRegisteredAppAction(service='docker', key='portainer', color='#008000'),
    )

    again = reducer(
        tinted,
        UpdateRegisteredAppAction(service='docker', key='portainer', color='#008000'),
    )

    assert again is tinted


def test_registration_carries_colour_through() -> None:
    """An app can be born tinted, not only restyled later."""
    state = reducer(None, InitAction())
    assert isinstance(state, MainState)

    result = reducer(
        state,
        RegisterRegularAppAction(
            label='Pi-hole',
            icon='󰇖',
            service='docker',
            key='pi_hole',
            color='#FFC107',
        ),
    )

    assert result.registered_apps['docker:pi_hole'].color == '#FFC107'
