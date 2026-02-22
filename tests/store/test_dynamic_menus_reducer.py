"""Tests for the dynamic menus reducer.

Pure unit tests for UpdateDynamicMenuAction and ClearDynamicMenuAction.
"""

from __future__ import annotations

import pytest
from redux import CompleteReducerResult, InitAction, InitializationActionError

from ubo_app.store.core.dynamic_menus_reducer import reducer
from ubo_app.store.core.types import (
    ClearDynamicMenuAction,
    DynamicMenuChangedEvent,
    DynamicMenuData,
    DynamicMenusState,
    MenuItemData,
    UpdateDynamicMenuAction,
)


def _init_state() -> DynamicMenusState:
    """Create initialized DynamicMenusState."""
    result = reducer(None, InitAction())
    assert isinstance(result, DynamicMenusState)
    return result


def _get_state(result: object) -> DynamicMenusState:
    if isinstance(result, CompleteReducerResult):
        return result.state
    assert isinstance(result, DynamicMenusState)
    return result


def _get_events(result: object) -> list:
    if isinstance(result, CompleteReducerResult):
        return list(result.events or ())
    return []


class TestInitAction:
    """Tests for initialization."""

    def test_init_creates_empty_state(self) -> None:
        """Verify InitAction creates state with empty menus dict."""
        state = _init_state()
        assert state.menus == {}

    def test_non_init_on_none_raises(self) -> None:
        """Verify non-init action on None state raises error."""
        with pytest.raises(InitializationActionError):
            reducer(None, UpdateDynamicMenuAction(menu_id='test'))


class TestUpdateDynamicMenuAction:
    """Tests for creating and updating dynamic menus."""

    def test_creates_new_menu(self) -> None:
        """Verify UpdateDynamicMenuAction creates a new menu entry."""
        state = _init_state()
        result = reducer(state, UpdateDynamicMenuAction(
            menu_id='wifi:connections',
            title='Wi-Fi',
            items=(
                MenuItemData(key='net1', label='Network1', icon='W'),
            ),
            placeholder='No networks',
        ))
        new_state = _get_state(result)
        assert 'wifi:connections' in new_state.menus
        menu = new_state.menus['wifi:connections']
        assert menu.title == 'Wi-Fi'
        assert len(menu.items) == 1
        assert menu.placeholder == 'No networks'

    def test_emits_changed_event(self) -> None:
        """Verify update action emits a DynamicMenuChangedEvent."""
        state = _init_state()
        result = reducer(state, UpdateDynamicMenuAction(
            menu_id='wifi:connections',
            title='Wi-Fi',
        ))
        events = _get_events(result)
        assert len(events) == 1
        assert isinstance(events[0], DynamicMenuChangedEvent)
        assert events[0].menu_id == 'wifi:connections'

    def test_replaces_existing_menu(self) -> None:
        """Verify updating an existing menu replaces its data."""
        state = _init_state()
        state = _get_state(reducer(state, UpdateDynamicMenuAction(
            menu_id='wifi:connections',
            title='Wi-Fi',
            items=(MenuItemData(key='n1', label='Net1', icon='W'),),
        )))
        state = _get_state(reducer(state, UpdateDynamicMenuAction(
            menu_id='wifi:connections',
            title='Wi-Fi Updated',
            items=(
                MenuItemData(key='n1', label='Net1', icon='W'),
                MenuItemData(key='n2', label='Net2', icon='W'),
            ),
        )))
        menu = state.menus['wifi:connections']
        assert menu.title == 'Wi-Fi Updated'
        assert len(menu.items) == 2

    def test_preserves_other_menus(self) -> None:
        """Verify adding a new menu preserves existing menus."""
        state = _init_state()
        state = _get_state(reducer(state, UpdateDynamicMenuAction(
            menu_id='wifi:connections',
            title='Wi-Fi',
        )))
        state = _get_state(reducer(state, UpdateDynamicMenuAction(
            menu_id='bt:devices',
            title='Bluetooth',
        )))
        assert 'wifi:connections' in state.menus
        assert 'bt:devices' in state.menus

    def test_heading_and_sub_heading(self) -> None:
        """Verify heading and sub_heading are stored correctly."""
        state = _init_state()
        result = reducer(state, UpdateDynamicMenuAction(
            menu_id='test:menu',
            title='Test',
            heading='Main Heading',
            sub_heading='Sub Heading',
        ))
        new_state = _get_state(result)
        menu = new_state.menus['test:menu']
        assert menu.heading == 'Main Heading'
        assert menu.sub_heading == 'Sub Heading'

    def test_creates_correct_menu_data(self) -> None:
        """Verify created menu is a DynamicMenuData with correct id."""
        state = _init_state()
        result = reducer(state, UpdateDynamicMenuAction(
            menu_id='test',
            title='Test',
        ))
        new_state = _get_state(result)
        menu = new_state.menus['test']
        assert isinstance(menu, DynamicMenuData)
        assert menu.menu_id == 'test'


class TestClearDynamicMenuAction:
    """Tests for clearing dynamic menus."""

    def test_removes_menu(self) -> None:
        """Verify ClearDynamicMenuAction removes the specified menu."""
        state = _init_state()
        state = _get_state(reducer(state, UpdateDynamicMenuAction(
            menu_id='wifi:connections',
            title='Wi-Fi',
        )))
        assert 'wifi:connections' in state.menus
        state = _get_state(reducer(state, ClearDynamicMenuAction(
            menu_id='wifi:connections',
        )))
        assert 'wifi:connections' not in state.menus

    def test_emits_event_on_clear(self) -> None:
        """Verify clear action emits a DynamicMenuChangedEvent."""
        state = _init_state()
        state = _get_state(reducer(state, UpdateDynamicMenuAction(
            menu_id='wifi:connections',
            title='Wi-Fi',
        )))
        result = reducer(state, ClearDynamicMenuAction(
            menu_id='wifi:connections',
        ))
        events = _get_events(result)
        assert len(events) == 1
        assert isinstance(events[0], DynamicMenuChangedEvent)
        assert events[0].menu_id == 'wifi:connections'

    def test_clear_nonexistent_returns_state(self) -> None:
        """Verify clearing a nonexistent menu returns unchanged state."""
        state = _init_state()
        result = reducer(state, ClearDynamicMenuAction(menu_id='nonexistent'))
        new_state = _get_state(result)
        assert new_state.menus == state.menus
        assert _get_events(result) == []

    def test_preserves_other_menus_on_clear(self) -> None:
        """Verify clearing one menu preserves other menus."""
        state = _init_state()
        state = _get_state(reducer(state, UpdateDynamicMenuAction(
            menu_id='wifi:connections',
            title='Wi-Fi',
        )))
        state = _get_state(reducer(state, UpdateDynamicMenuAction(
            menu_id='bt:devices',
            title='Bluetooth',
        )))
        state = _get_state(reducer(state, ClearDynamicMenuAction(
            menu_id='wifi:connections',
        )))
        assert 'wifi:connections' not in state.menus
        assert 'bt:devices' in state.menus
