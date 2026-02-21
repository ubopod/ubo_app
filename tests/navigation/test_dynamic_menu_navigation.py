"""Tests for dynamic menu navigation.

Tests that dynamic menus interact correctly with the view computation
via the dynamic menus reducer and view helpers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from redux import CompleteReducerResult, InitAction

from ubo_app.store.core.dynamic_menus_reducer import reducer as dynamic_menus_reducer
from ubo_app.store.core.types import (
    ClearDynamicMenuAction,
    DynamicMenuData,
    DynamicMenusState,
    MenuItemData,
    StackPushMenuAction,
    UpdateDynamicMenuAction,
)
from ubo_app.store.core.view_helpers import (
    find_dynamic_menu_for_position,
    get_dynamic_menu_id_for_stack,
)
from ubo_app.store.core.view_registry import (
    _registry_container,
    register_path_menu_matcher,
)

if TYPE_CHECKING:
    from tests.navigation.conftest import ReducerRunner


def _clean_registry() -> None:
    if _registry_container[0] is not None:
        _registry_container[0].path_menu_matchers.clear()


def _init_dynamic_state() -> DynamicMenusState:
    result = dynamic_menus_reducer(None, InitAction())
    assert isinstance(result, DynamicMenusState)
    return result


class TestDynamicMenuRegistration:
    """Tests for registering and finding dynamic menus via navigation."""

    def test_dynamic_menu_found_by_path(self, nav: ReducerRunner) -> None:
        """Find dynamic menu when navigating to path with registered matcher."""
        _clean_registry()
        unregister = register_path_menu_matcher(
            'test:wifi',
            lambda path: (
                'wifi:list'
                if path == ('main', 'settings', 'network', 'wifi')
                else None
            ),
        )
        try:
            nav.dispatch(StackPushMenuAction(menu_key='main'))
            nav.dispatch(StackPushMenuAction(menu_key='settings'))
            nav.dispatch(StackPushMenuAction(menu_key='network'))
            nav.dispatch(StackPushMenuAction(menu_key='wifi'))

            dynamic_state = DynamicMenusState(menus={
                'wifi:list': DynamicMenuData(
                    menu_id='wifi:list',
                    title='Wi-Fi Networks',
                    items=(MenuItemData(key='net1', label='MyNetwork', icon='W'),),
                ),
            })

            result = find_dynamic_menu_for_position(
                nav.state, dynamic_state, nav.state.stack,
            )
            assert result is not None
            assert result[0] == 'wifi:list'
            assert result[1] == 'Wi-Fi Networks'
        finally:
            unregister()

    def test_no_dynamic_menu_at_root(self, nav: ReducerRunner) -> None:
        """At root/home, no dynamic menu should match."""
        _clean_registry()
        dynamic_state = DynamicMenusState(menus={
            'test': DynamicMenuData(menu_id='test', title='Test'),
        })
        result = find_dynamic_menu_for_position(
            nav.state, dynamic_state, nav.state.stack,
        )
        assert result is None


class TestDynamicMenuUpdate:
    """Tests for updating dynamic menu content."""

    def test_update_adds_items(self) -> None:
        """Verify updating a dynamic menu adds items to the menu state."""
        state = _init_dynamic_state()
        result = dynamic_menus_reducer(state, UpdateDynamicMenuAction(
            menu_id='wifi:list',
            title='Wi-Fi',
            items=(
                MenuItemData(key='n1', label='Net1', icon='W'),
                MenuItemData(key='n2', label='Net2', icon='W'),
            ),
        ))
        assert isinstance(result, CompleteReducerResult)
        assert len(result.state.menus['wifi:list'].items) == 2

    def test_update_replaces_items(self) -> None:
        """Verify updating a dynamic menu replaces existing items."""
        state = _init_dynamic_state()
        result = dynamic_menus_reducer(state, UpdateDynamicMenuAction(
            menu_id='wifi:list',
            title='Wi-Fi',
            items=(MenuItemData(key='old', label='Old', icon='W'),),
        ))
        assert isinstance(result, CompleteReducerResult)
        state = result.state

        result = dynamic_menus_reducer(state, UpdateDynamicMenuAction(
            menu_id='wifi:list',
            title='Wi-Fi',
            items=(MenuItemData(key='new', label='New', icon='W'),),
        ))
        assert isinstance(result, CompleteReducerResult)
        items = result.state.menus['wifi:list'].items
        assert len(items) == 1
        assert items[0] is not None
        assert items[0].key == 'new'


class TestDynamicMenuClear:
    """Tests for clearing dynamic menus."""

    def test_clear_removes_menu(self) -> None:
        """Verify clearing a dynamic menu removes it from the state."""
        state = _init_dynamic_state()
        result = dynamic_menus_reducer(state, UpdateDynamicMenuAction(
            menu_id='wifi:list',
            title='Wi-Fi',
        ))
        assert isinstance(result, CompleteReducerResult)
        state = result.state

        result = dynamic_menus_reducer(state, ClearDynamicMenuAction(
            menu_id='wifi:list',
        ))
        assert isinstance(result, CompleteReducerResult)
        assert 'wifi:list' not in result.state.menus

    def test_clear_nonexistent_is_noop(self) -> None:
        """Verify clearing a nonexistent menu returns state unchanged."""
        state = _init_dynamic_state()
        result = dynamic_menus_reducer(state, ClearDynamicMenuAction(
            menu_id='nonexistent',
        ))
        assert isinstance(result, DynamicMenusState)


class TestPathMatcherPriority:
    """Tests for path matcher priority ordering."""

    def test_higher_priority_wins(self, nav: ReducerRunner) -> None:
        """Verify higher priority path matcher takes precedence over lower priority."""
        _clean_registry()
        # Low priority matcher
        unreg1 = register_path_menu_matcher(
            'low:matcher',
            lambda path: 'low:menu' if path == ('main',) else None,
            priority=1,
        )
        # High priority matcher
        unreg2 = register_path_menu_matcher(
            'high:matcher',
            lambda path: 'high:menu' if path == ('main',) else None,
            priority=10,
        )
        try:
            nav.dispatch(StackPushMenuAction(menu_key='main'))
            result = get_dynamic_menu_id_for_stack(nav.state)
            assert result == 'high:menu'
        finally:
            unreg1()
            unreg2()
