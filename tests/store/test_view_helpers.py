"""Tests for view_helpers.py functions.

Pure unit tests for title normalization, path matching, and dynamic menu lookup.
"""

from __future__ import annotations

from ubo_app.store.core.types import (
    DynamicMenuData,
    DynamicMenusState,
    MainState,
    MenuStackItem,
)
from ubo_app.store.core.view_helpers import (
    find_dynamic_menu_by_title,
    find_dynamic_menu_for_position,
    get_dynamic_menu_id_for_stack,
    normalize_menu_title,
    strip_nerd_font_icons,
)
from ubo_app.store.core.view_registry import (
    _registry_container,
    register_path_menu_matcher,
)


def _clean_registry() -> None:
    """Reset the view registry singleton for test isolation."""
    if _registry_container[0] is not None:
        _registry_container[0].path_menu_matchers.clear()


class TestStripNerdFontIcons:
    """Tests for strip_nerd_font_icons."""

    def test_plain_text_unchanged(self) -> None:
        """Verify plain text is returned unchanged."""
        assert strip_nerd_font_icons('Hello') == 'Hello'

    def test_strips_leading_icons_from_charset(self) -> None:
        """Verify leading nerd font icons are stripped."""
        from ubo_app.store.core.constants import NERD_FONT_ICON_CHARS

        # Use actual characters from the charset
        icon = NERD_FONT_ICON_CHARS[0]
        assert strip_nerd_font_icons(f'{icon}Main') == 'Main'

    def test_strips_multiple_leading_icons(self) -> None:
        """Verify multiple leading nerd font icons are stripped."""
        from ubo_app.store.core.constants import NERD_FONT_ICON_CHARS

        icons = NERD_FONT_ICON_CHARS[:3]
        assert strip_nerd_font_icons(f'{icons}Main') == 'Main'

    def test_empty_string(self) -> None:
        """Verify empty string returns empty string."""
        assert strip_nerd_font_icons('') == ''

    def test_preserves_text_with_unknown_icons(self) -> None:
        """Icons not in the charset are preserved."""
        result = strip_nerd_font_icons('XMain')
        assert result == 'XMain'

    def test_strips_spaces_after_icons(self) -> None:
        """Verify spaces between icons and text are stripped."""
        from ubo_app.store.core.constants import NERD_FONT_ICON_CHARS

        icon = NERD_FONT_ICON_CHARS[0]
        result = strip_nerd_font_icons(f'{icon} Main')
        assert result == 'Main'


class TestNormalizeMenuTitle:
    """Tests for normalize_menu_title."""

    def test_plain_title(self) -> None:
        """Verify plain title is returned unchanged."""
        assert normalize_menu_title('Settings') == 'Settings'

    def test_icon_prefix(self) -> None:
        """Verify icon prefix is stripped from title."""
        from ubo_app.store.core.constants import NERD_FONT_ICON_CHARS

        icon = NERD_FONT_ICON_CHARS[0]
        assert normalize_menu_title(f'{icon}Main') == 'Main'

    def test_empty_string(self) -> None:
        """Verify empty string normalizes to empty string."""
        assert normalize_menu_title('') == ''


class TestFindDynamicMenuByTitle:
    """Tests for find_dynamic_menu_by_title."""

    def test_finds_by_exact_title(self) -> None:
        """Verify lookup by exact title returns the menu id."""
        state = DynamicMenusState(menus={
            'wifi:list': DynamicMenuData(menu_id='wifi:list', title='Wi-Fi'),
        })
        result = find_dynamic_menu_by_title('Wi-Fi', state)
        assert result == 'wifi:list'

    def test_finds_with_icon_prefix(self) -> None:
        """Verify title with icon prefix is matched correctly."""
        from ubo_app.store.core.constants import NERD_FONT_ICON_CHARS

        icon = NERD_FONT_ICON_CHARS[0]
        state = DynamicMenusState(menus={
            'main:menu': DynamicMenuData(menu_id='main:menu', title=f'{icon}Main'),
        })
        # Normalized search title matches normalized menu title
        result = find_dynamic_menu_by_title(f'{icon}Main', state)
        assert result == 'main:menu'

    def test_returns_none_for_missing(self) -> None:
        """Verify missing title returns None."""
        state = DynamicMenusState(menus={
            'wifi:list': DynamicMenuData(menu_id='wifi:list', title='Wi-Fi'),
        })
        result = find_dynamic_menu_by_title('Bluetooth', state)
        assert result is None

    def test_empty_menus(self) -> None:
        """Verify search in empty menus returns None."""
        state = DynamicMenusState(menus={})
        result = find_dynamic_menu_by_title('anything', state)
        assert result is None


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

    def test_title_based_fallback(self) -> None:
        """When path matching fails, falls back to title matching."""
        _clean_registry()
        from ubo_gui.menu.types import HeadlessMenu, SubMenuItem

        test_menu = HeadlessMenu(
            title='Root',
            items=[
                SubMenuItem(
                    key='wifi', label='Wi-Fi', icon='W',
                    sub_menu=HeadlessMenu(title='Wi-Fi', items=[]),
                ),
            ],
        )
        stack = (
            MenuStackItem(id='root', menu_key='', page_index=0),
            MenuStackItem(id='w', menu_key='wifi', page_index=0),
        )
        dynamic_state = DynamicMenusState(menus={
            'wifi:connections': DynamicMenuData(
                menu_id='wifi:connections',
                title='Wi-Fi',
            ),
        })
        main_state = MainState(
            menu=test_menu,
            stack=stack,
            path=('wifi',),
        )
        result = find_dynamic_menu_for_position(
            main_state, dynamic_state, stack,
        )
        assert result is not None
        assert result == ('wifi:connections', 'Wi-Fi')
