"""Fixtures for navigation integration tests.

These tests call the reducer directly to test navigation flows,
avoiding the singleton store and Kivy dependencies entirely.

NOTE: reducer.py imports menus.py which imports store.main, creating a
circular import. We pre-populate sys.modules with a fake menus module
before importing the reducer.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest
from redux import CompleteReducerResult, InitAction
from ubo_gui.menu.types import HeadlessMenu, SubMenuItem, menu_items

from ubo_app.store.core.constants import PAGE_SIZE
from ubo_app.store.core.menu_adapter import (
    get_current_menu_from_stack,
    item_to_menu_item_data,
)
from ubo_app.store.core.types import (
    ApplicationStackItem,
    ApplicationViewData,
    HomeViewData,
    MainState,
    MenuStackItem,
    MenuViewData,
    NotificationStackItem,
    NotificationViewData,
    ViewData,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.store.core.types import MainAction, MainEvent


# ============================================================================
# Test Menu Tree
# ============================================================================
# A self-contained menu tree for testing, avoiding imports from menus.py
# which trigger store autoruns at module level.

WIFI_MENU = HeadlessMenu(title='Wi-Fi', items=[], placeholder='No networks')
BT_MENU = HeadlessMenu(title='Bluetooth', items=[], placeholder='No devices')
NETWORK_MENU = HeadlessMenu(
    title='Network',
    items=[
        SubMenuItem(key='wifi', label='Wi-Fi', icon='W', sub_menu=WIFI_MENU),
        SubMenuItem(key='bt', label='Bluetooth', icon='B', sub_menu=BT_MENU),
    ],
)
SYSTEM_MENU = HeadlessMenu(title='System', items=[], placeholder='No settings')

APPS_MENU = HeadlessMenu(title='Apps', items=[], placeholder='No apps')
SETTINGS_MENU = HeadlessMenu(
    title='Settings',
    items=[
        SubMenuItem(key='network', label='Network', icon='N',
                    sub_menu=NETWORK_MENU),
        SubMenuItem(key='system', label='System', icon='S',
                    sub_menu=SYSTEM_MENU),
    ],
)

MAIN_MENU = HeadlessMenu(
    title='Main',
    items=[
        SubMenuItem(key='apps', label='Apps', icon='A', sub_menu=APPS_MENU),
        SubMenuItem(key='settings', label='Settings', icon='S',
                    sub_menu=SETTINGS_MENU),
    ],
)

POWER_MENU = HeadlessMenu(
    title='Power',
    items=[
        SubMenuItem(key='reboot', label='Reboot', icon='R',
                    sub_menu=HeadlessMenu(title='Confirm Reboot', items=[])),
        SubMenuItem(key='poweroff', label='Power Off', icon='P',
                    sub_menu=HeadlessMenu(title='Confirm Power Off', items=[])),
    ],
)

NOTIFICATIONS_MENU = HeadlessMenu(
    title='Notifications',
    items=[],
    placeholder='No notifications',
)

TEST_HOME_MENU = HeadlessMenu(
    title='Home',
    items=[
        SubMenuItem(key='main', label='Main', icon='M', sub_menu=MAIN_MENU),
        SubMenuItem(key='notifications', label='Notifications', icon='N',
                    sub_menu=NOTIFICATIONS_MENU),
        SubMenuItem(key='power', label='Power', icon='P', sub_menu=POWER_MENU),
    ],
)


# ============================================================================
# Import reducer with circular-import workaround
# ============================================================================

def _import_reducer() -> Callable:
    """Import the reducer, breaking the circular import chain."""
    menus_key = 'ubo_app.store.core.menus'
    already_loaded = menus_key in sys.modules

    if not already_loaded:
        from types import ModuleType

        fake_menus = ModuleType(menus_key)
        fake_menus.HOME_MENU = TEST_HOME_MENU  # type: ignore[attr-defined]
        sys.modules[menus_key] = fake_menus

    from ubo_app.store.core.reducer import reducer
    return reducer


reducer = _import_reducer()


# ============================================================================
# Local compute_view_from_stack (avoids circular import)
# ============================================================================

def compute_view_from_stack(state: MainState) -> ViewData:
    """Compute view data from the current stack and menu state.

    Local copy to avoid importing from reducer.py which may not have
    been fully loaded yet due to circular imports.
    """
    stack = state.stack
    menu = state.menu

    if not stack:
        return HomeViewData()

    top_item = stack[-1]

    if isinstance(top_item, ApplicationStackItem):
        extra_data: dict[str, str] = {}
        for k, v in top_item.initialization_kwargs.items():
            extra_data[k] = str(v)
        return ApplicationViewData(
            application_id=top_item.application_id,
            show_status_bar=False,
            extra_data=extra_data,
        )

    if isinstance(top_item, NotificationStackItem):
        return NotificationViewData(
            notification_id=top_item.notification_id,
            show_status_bar=False,
        )

    if not isinstance(top_item, MenuStackItem):
        return HomeViewData()

    current_menu = get_current_menu_from_stack(menu, stack)
    if current_menu is None:
        return HomeViewData()

    items = menu_items(current_menu)
    page_index = top_item.page_index

    menu_item_data = tuple(
        item_to_menu_item_data(item, i) for i, item in enumerate(items)
    )

    title_value = current_menu.title
    title = title_value() if callable(title_value) else (title_value or '')

    heading: str | None = None
    sub_heading: str | None = None
    heading_val = getattr(current_menu, 'heading', None)
    if heading_val is not None:
        heading = str(heading_val() if callable(heading_val) else heading_val)
    sub_heading_val = getattr(current_menu, 'sub_heading', None)
    if sub_heading_val is not None:
        sub_heading = str(
            sub_heading_val() if callable(sub_heading_val) else sub_heading_val,
        )

    total_pages = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)

    depth = len([i for i in stack if isinstance(i, MenuStackItem)])
    is_home = depth <= 1

    if is_home:
        home_items = tuple(item for item in menu_item_data if item is not None)
        return HomeViewData(
            show_status_bar=True,
            menu_items=home_items,
            cpu_percent=0.0,
            ram_percent=0.0,
            volume_level=0.0,
        )

    return MenuViewData(
        show_status_bar=page_index == 0,
        title=cast('str', title),
        heading=heading,
        sub_heading=sub_heading,
        items=menu_item_data,
        page_index=page_index,
        total_pages=total_pages,
    )


# ============================================================================
# Reducer Wrapper
# ============================================================================


class ReducerRunner:
    """Wraps the reducer to provide a convenient dispatch/assert interface.

    This replaces the need for a full store in navigation tests.
    Tracks state and events from each dispatch.
    """

    def __init__(self, state: MainState) -> None:
        """Initialize the runner with the given state."""
        self.state = state
        self.last_events: list[MainEvent] = []
        self.all_events: list[MainEvent] = []

    def dispatch(self, action: MainAction) -> MainState:
        """Dispatch an action through the reducer, updating state."""
        result = reducer(self.state, action)
        if isinstance(result, CompleteReducerResult):
            self.state = result.state
            self.last_events = list(result.events)
            self.all_events.extend(result.events)
        elif isinstance(result, MainState):
            self.state = result
            self.last_events = []
        return self.state

    @property
    def view(self) -> ViewData:
        """Get the current computed view."""
        return compute_view_from_stack(self.state)

    @property
    def current_view(self) -> ViewData | None:
        """Get the view stored in state (set by reducer on stack changes)."""
        return self.state.current_view

    def clear_events(self) -> None:
        """Clear tracked events."""
        self.last_events.clear()
        self.all_events.clear()


@pytest.fixture
def nav() -> ReducerRunner:
    """Create a ReducerRunner with initialized state and test menu tree.

    Usage::

        def test_something(nav: ReducerRunner):
            nav.dispatch(StackPushMenuAction(menu_key='main'))
            assert isinstance(nav.view, MenuViewData)
    """
    result = reducer(None, InitAction())
    assert isinstance(result, MainState)
    state = replace(result, menu=TEST_HOME_MENU)
    return ReducerRunner(state)


class EventCapture:
    """Captures events of a specific type from a ReducerRunner."""

    def __init__(self) -> None:
        """Initialize with an empty events list."""
        self.events: list = []

    def capture_from(self, runner: ReducerRunner, event_type: type) -> list:
        """Return events of the given type from runner's last dispatch."""
        return [e for e in runner.last_events if isinstance(e, event_type)]

    def all_of_type(self, runner: ReducerRunner, event_type: type) -> list:
        """Return all events of the given type from runner's history."""
        return [e for e in runner.all_events if isinstance(e, event_type)]


@pytest.fixture
def events() -> EventCapture:
    """Create an EventCapture helper."""
    return EventCapture()
