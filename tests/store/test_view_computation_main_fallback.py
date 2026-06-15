"""Regression tests for the top-level-menu view-computation fallback.

These call the *production* ``compute_view_from_root_state`` (not a test
re-implementation) to lock in the fix for the blank/stuck "main" view: a
top-level menu key (e.g. 'main') pushed onto a non-root stack by a racing
client must still resolve to its real menu instead of an empty view.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from ubo_app.store.core.stack_ops import create_root_stack_item, push_menu
from ubo_app.store.core.types import (
    DynamicMenuData,
    DynamicMenusState,
    MainState,
    MenuItemData,
    MenuViewData,
)
from ubo_app.store.core.view_computation import compute_view_from_root_state
from ubo_app.store.core.view_registry import (
    _registry_container,
    register_path_menu_matcher,
)

if TYPE_CHECKING:
    from ubo_app.store.main import RootState

MAIN_MENU = DynamicMenuData(
    menu_id='main:menu',
    title='Main',
    items=(
        MenuItemData(key='apps', label='Apps', icon='A'),
        MenuItemData(key='settings', label='Settings', icon='S'),
        MenuItemData(key='about', label='About', icon='B'),
    ),
)


@pytest.fixture(autouse=True)
def _stub_menus_module() -> object:
    """Satisfy ``compute_view_from_root_state``'s deferred menus import cheaply.

    The function does ``from ubo_app.store.core.menus import HOME_MENU_ID`` on
    every call (only used in the home/depth-1 branch, which these tests never
    reach). Importing the real ``menus`` module has heavy side effects (it spins
    up store machinery and hangs or trips the main-thread guard in this bare unit
    tier), so we inject a minimal stub providing just that constant.
    """
    if 'ubo_app.store.core.menus' in sys.modules:
        yield
        return
    stub = ModuleType('ubo_app.store.core.menus')
    stub.HOME_MENU_ID = 'home:main'  # type: ignore[attr-defined]
    sys.modules['ubo_app.store.core.menus'] = stub
    try:
        yield
    finally:
        del sys.modules['ubo_app.store.core.menus']


def _clean_registry() -> None:
    """Reset the view registry singleton for test isolation."""
    if _registry_container[0] is not None:
        _registry_container[0].path_menu_matchers.clear()


def _state(main: MainState) -> RootState:
    """Build a minimal RootState stand-in for view computation.

    For a MenuStackItem top, ``compute_view_from_root_state`` only reads
    ``state.main`` and ``state.dynamic_menus`` (and probes ``notifications``
    via ``hasattr``), so a namespace with those two slices is sufficient.
    """
    return cast(
        'RootState',
        SimpleNamespace(
            main=main,
            dynamic_menus=DynamicMenusState(menus={'main:menu': MAIN_MENU}),
        ),
    )


def test_main_resolves_when_pushed_onto_non_root_stack() -> None:
    """'main' pushed at depth > 1 renders the real Main menu, not a blank view.

    Reproduces the original bug: the web UI auto-navigate pushes
    ``StackPushMenuAction('main')`` onto a non-root stack, yielding path
    ('settings', 'main') that no full-path matcher recognises.
    """
    _clean_registry()
    # Only ('main',) is registered — mirrors the core path matcher. The full
    # ('settings', 'main') path is deliberately unmatched.
    unregister = register_path_menu_matcher(
        'test:core',
        lambda path: 'main:menu' if path == ('main',) else None,
    )
    try:
        main = MainState(stack=create_root_stack_item())
        main = push_menu(main, 'settings')
        main = push_menu(main, 'main')
        assert main.path == ('settings', 'main')

        view = compute_view_from_root_state(_state(main))

        assert isinstance(view, MenuViewData)
        assert view.title == 'Main'
        assert len(view.items) == len(MAIN_MENU.items)
    finally:
        unregister()


def test_unresolvable_key_still_returns_empty_view() -> None:
    """A key with no single-element matcher does not render a wrong menu.

    Guards the "safe" property of the fallback: it only rescues genuine
    top-level keys; anything else correctly falls through to the empty view.
    """
    _clean_registry()
    unregister = register_path_menu_matcher(
        'test:core',
        lambda path: 'main:menu' if path == ('main',) else None,
    )
    try:
        main = MainState(stack=create_root_stack_item())
        main = push_menu(main, 'settings')
        main = push_menu(main, 'unknown')
        assert main.path == ('settings', 'unknown')

        view = compute_view_from_root_state(_state(main))

        assert isinstance(view, MenuViewData)
        assert view.title == ''
        assert view.items == ()
    finally:
        unregister()
