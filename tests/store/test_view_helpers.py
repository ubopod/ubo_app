"""Tests for view_helpers.py functions.

Pure unit tests for path matching and dynamic menu lookup.
"""

from __future__ import annotations

from ubo_app.store.core.types import (
    DynamicMenuData,
    DynamicMenusState,
    MainState,
)
from ubo_app.store.core.view_helpers import (
    find_dynamic_menu_for_position,
    get_dynamic_menu_id_for_stack,
)
from ubo_app.store.core.view_registry import (
    _registry_container,
    register_path_menu_matcher,
)


def _clean_registry() -> None:
    """Reset the view registry singleton for test isolation."""
    if _registry_container[0] is not None:
        _registry_container[0].path_menu_matchers.clear()


class TestGetDynamicMenuIdForStack:
    """Tests for get_dynamic_menu_id_for_stack."""

    def test_empty_path_returns_none(self) -> None:
        """Verify empty path returns None."""
        state = MainState(path=())
        result = get_dynamic_menu_id_for_stack(state)
        assert result is None

    def test_with_registered_matcher(self) -> None:
        """Verify registered path matcher returns correct menu id."""
        _clean_registry()
        unregister = register_path_menu_matcher(
            'test:matcher',
            lambda path: 'wifi:list' if path == ('main', 'wifi') else None,
        )
        try:
            state = MainState(path=('main', 'wifi'))
            result = get_dynamic_menu_id_for_stack(state)
            assert result == 'wifi:list'
        finally:
            unregister()

    def test_no_matcher_returns_none(self) -> None:
        """Verify no matching path matcher returns None."""
        _clean_registry()
        state = MainState(path=('main', 'unknown'))
        result = get_dynamic_menu_id_for_stack(state)
        assert result is None


class TestFindDynamicMenuForPosition:
    """Tests for find_dynamic_menu_for_position."""

    def test_returns_none_when_no_dynamic_menus_state(self) -> None:
        """Verify None dynamic state returns None."""
        state = MainState(path=('main',))
        result = find_dynamic_menu_for_position(state, None, state.stack)
        assert result is None

    def test_path_based_match(self) -> None:
        """Verify path-based match returns menu id and title."""
        _clean_registry()
        unregister = register_path_menu_matcher(
            'test:matcher',
            lambda path: 'wifi:list' if path == ('main', 'wifi') else None,
        )
        try:
            dynamic_state = DynamicMenusState(menus={
                'wifi:list': DynamicMenuData(
                    menu_id='wifi:list',
                    title='Wi-Fi',
                ),
            })
            main_state = MainState(path=('main', 'wifi'))
            result = find_dynamic_menu_for_position(
                main_state, dynamic_state, main_state.stack,
            )
            assert result is not None
            assert result == ('wifi:list', 'Wi-Fi')
        finally:
            unregister()

    def test_returns_none_for_empty_dynamic_state(self) -> None:
        """Verify empty dynamic menus state returns None."""
        _clean_registry()
        state = MainState(path=('main',))
        dynamic_state = DynamicMenusState(menus={})
        result = find_dynamic_menu_for_position(state, dynamic_state, state.stack)
        assert result is None

    def test_path_match_not_in_dynamic_menus_falls_through(self) -> None:
        """Path matcher returns a menu_id not present in dynamic_menus_state."""
        _clean_registry()
        unregister = register_path_menu_matcher(
            'test:matcher',
            lambda path: 'missing:menu' if path == ('main',) else None,
        )
        try:
            dynamic_state = DynamicMenusState(menus={})
            main_state = MainState(path=('main',))
            result = find_dynamic_menu_for_position(
                main_state, dynamic_state, main_state.stack,
            )
            assert result is None
        finally:
            unregister()
