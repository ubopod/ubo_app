"""Fixtures for navigation integration tests.

These tests call the reducer directly to test navigation flows,
avoiding the singleton store and Kivy dependencies entirely.

NOTE: reducer.py imports from menus.py which imports store.main, creating a
circular import. We pre-populate sys.modules with a fake menus module
before importing the reducer.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest
from redux import CompleteReducerResult, InitAction

from ubo_app.store.core.constants import (
    MENU_NAVIGATE_PREFIX,
    MENU_SELECT_PREFIX,
    compute_total_pages,
)
from ubo_app.store.core.types import (
    ApplicationStackItem,
    ApplicationViewData,
    ChatStackItem,
    ChatViewData,
    DynamicMenuData,
    HomeViewData,
    InstructionStackItem,
    InstructionViewData,
    MainState,
    MenuItemData,
    MenuStackItem,
    MenuViewData,
    NotificationStackItem,
    NotificationViewData,
    PromptStackItem,
    PromptViewData,
    RenderStackItem,
    RenderViewData,
    StackPushMenuAction,
    ViewData,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from ubo_app.store.core.types import MainAction, MainEvent


# ============================================================================
# Test Dynamic Menus (replaces legacy menu tree)
# ============================================================================
# Define test menus as dynamic menu data, matching the old tree structure.

TEST_DYNAMIC_MENUS: dict[str, DynamicMenuData] = {
    'home:main': DynamicMenuData(
        menu_id='home:main',
        title='Home',
        items=(
            MenuItemData(key='main', label='Main', icon='M', is_short=True,
                         action_id=f'{MENU_NAVIGATE_PREFIX}main'),
            MenuItemData(
                key='notifications', label='Notifications', icon='N',
                is_short=True,
                action_id=f'{MENU_NAVIGATE_PREFIX}notifications',
            ),
            MenuItemData(key='power', label='Power', icon='P', is_short=True,
                         action_id=f'{MENU_NAVIGATE_PREFIX}power'),
        ),
    ),
    'main:menu': DynamicMenuData(
        menu_id='main:menu',
        title='Main',
        items=(
            MenuItemData(key='apps', label='Apps', icon='A',
                         action_id=f'{MENU_NAVIGATE_PREFIX}apps'),
            MenuItemData(key='settings', label='Settings', icon='S',
                         action_id=f'{MENU_NAVIGATE_PREFIX}settings'),
        ),
    ),
    'apps:list': DynamicMenuData(
        menu_id='apps:list',
        title='Apps',
        items=tuple(
            MenuItemData(key=f'app{i}', label=f'App {i}', icon=str(i),
                         action_id=f'{MENU_SELECT_PREFIX}app{i}')
            for i in range(7)  # 7 items -> 3 pages (PAGE_SIZE=3)
        ),
    ),
    'settings:categories': DynamicMenuData(
        menu_id='settings:categories',
        title='Settings',
        items=(
            MenuItemData(key='network', label='Network', icon='N',
                         action_id=f'{MENU_NAVIGATE_PREFIX}settings:network'),
            MenuItemData(key='system', label='System', icon='S',
                         action_id=f'{MENU_NAVIGATE_PREFIX}settings:system'),
        ),
    ),
    'settings:network': DynamicMenuData(
        menu_id='settings:network',
        title='Network',
        items=(
            MenuItemData(key='wifi', label='Wi-Fi', icon='W',
                         action_id='menu:select:wifi'),
            MenuItemData(key='bt', label='Bluetooth', icon='B',
                         action_id='menu:select:bt'),
        ),
    ),
    'settings:system': DynamicMenuData(
        menu_id='settings:system',
        title='System',
        items=(),
        placeholder='No settings',
    ),
    'wifi:list': DynamicMenuData(
        menu_id='wifi:list',
        title='Wi-Fi',
        items=(),
        placeholder='No networks',
    ),
    'bt:list': DynamicMenuData(
        menu_id='bt:list',
        title='Bluetooth',
        items=(),
        placeholder='No devices',
    ),
    'notifications:list': DynamicMenuData(
        menu_id='notifications:list',
        title='Notifications',
        items=(),
        placeholder='No notifications',
    ),
    'power:options': DynamicMenuData(
        menu_id='power:options',
        title='Power',
        items=(
            MenuItemData(key='reboot', label='Reboot', icon='R',
                         action_id='power:reboot'),
            MenuItemData(key='poweroff', label='Power Off', icon='P',
                         action_id='power:off'),
        ),
    ),
}

# Path-to-menu-id mappings for the test menus
TEST_PATH_MAPPINGS: dict[tuple[str, ...], str] = {
    ('main',): 'main:menu',
    ('main', 'apps'): 'apps:list',
    ('main', 'settings'): 'settings:categories',
    ('main', 'settings', 'network'): 'settings:network',
    ('main', 'settings', 'system'): 'settings:system',
    ('main', 'settings', 'network', 'wifi'): 'wifi:list',
    ('main', 'settings', 'network', 'bt'): 'bt:list',
    ('notifications',): 'notifications:list',
    ('power',): 'power:options',
}


# ============================================================================
# Import reducer with circular-import workaround
# ============================================================================

def _import_reducer() -> Callable:
    """Import the reducer, breaking the circular import chain.

    Installs a fake menus module temporarily so the reducer can be imported
    without triggering Kivy initialization via store.main. ALL newly loaded
    modules are removed from sys.modules after import so integration tests
    get fresh imports of the real modules.
    """
    menus_key = 'ubo_app.store.core.menus'
    already_loaded = menus_key in sys.modules
    modules_before = set(sys.modules)

    if not already_loaded:
        from types import ModuleType

        fake_menus = ModuleType(menus_key)
        sys.modules[menus_key] = fake_menus

    from ubo_app.store.core.reducer import reducer

    # Clean up: remove ALL modules loaded during this import so they
    # don't interfere with integration tests that need real modules
    if not already_loaded:
        for mod in set(sys.modules) - modules_before:
            del sys.modules[mod]

    return reducer


reducer = _import_reducer()


# ============================================================================
# View computation from dynamic menus (replaces legacy compute_view_from_stack)
# ============================================================================

def compute_view_from_dynamic_menus(  # noqa: C901
    state: MainState,
    dynamic_menus: dict[str, DynamicMenuData],
    path_mappings: dict[tuple[str, ...], str],
) -> ViewData:
    """Compute view data from dynamic menus instead of the legacy menu tree.

    This mirrors the logic in view_computation.py but uses local test data.
    """
    stack = state.stack

    if not stack:
        return HomeViewData()

    top_item = stack[-1]

    if isinstance(top_item, ApplicationStackItem):
        return ApplicationViewData(
            application_id=top_item.application_id,
            show_status_bar=False,
            extra_data=dict(top_item.initialization_kwargs),
        )

    if isinstance(top_item, RenderStackItem):
        return RenderViewData(
            kind=top_item.kind,
            title=top_item.title,
            show_status_bar=False,
            props=dict(top_item.props),
            items=top_item.items,
            stream_id=top_item.stream_id,
            stack_depth=len(stack),
        )

    if isinstance(top_item, ChatStackItem):
        return ChatViewData(
            scroll_offset=top_item.scroll_offset,
            stack_depth=len(stack),
        )

    if isinstance(top_item, NotificationStackItem):
        return NotificationViewData(
            notification_id=top_item.notification_id,
            show_status_bar=False,
        )

    if isinstance(top_item, InstructionStackItem):
        return InstructionViewData(
            title=top_item.title,
            instruction=top_item.instruction,
            icon=top_item.icon,
            spinner=top_item.spinner,
            timeout_seconds=top_item.timeout_seconds,
            progress_text=top_item.progress_text,
            footer_text=top_item.footer_text,
            stack_depth=len(stack),
        )

    if isinstance(top_item, PromptStackItem):
        return PromptViewData(
            title=top_item.title,
            prompt=top_item.prompt,
            icon=top_item.icon,
            items=top_item.items,
            stack_depth=len(stack),
        )

    if not isinstance(top_item, MenuStackItem):
        return HomeViewData()

    # Check depth
    depth = len([i for i in stack if isinstance(i, MenuStackItem)])
    if depth <= 1:
        home_menu = dynamic_menus.get('home:main')
        home_items = home_menu.items if home_menu else ()
        return HomeViewData(
            show_status_bar=True,
            menu_items=tuple(item for item in home_items if item is not None),
            cpu_percent=0.0,
            ram_percent=0.0,
            volume_level=0.0,
        )

    # Look up dynamic menu by path
    path = state.path
    menu_id = path_mappings.get(path)
    if menu_id:
        dynamic_menu = dynamic_menus.get(menu_id)
        if dynamic_menu:
            items = dynamic_menu.items
            page_index = top_item.page_index
            total_pages = compute_total_pages(
                len(items),
                is_headed=dynamic_menu.heading is not None,
            )
            return MenuViewData(
                show_status_bar=page_index == 0,
                title=dynamic_menu.title,
                heading=dynamic_menu.heading,
                sub_heading=dynamic_menu.sub_heading,
                items=items,
                page_index=page_index,
                total_pages=total_pages,
            )

    # No match - return empty menu view
    return MenuViewData(
        show_status_bar=True,
        title='',
        items=(),
        page_index=0,
        total_pages=1,
    )


# ============================================================================
# Reducer Wrapper
# ============================================================================


class ReducerRunner:
    """Wraps the reducer to provide a convenient dispatch/assert interface.

    This replaces the need for a full store in navigation tests.
    Tracks state and events from each dispatch.
    """

    def __init__(
        self,
        state: MainState,
        dynamic_menus: dict[str, DynamicMenuData] | None = None,
        path_mappings: dict[tuple[str, ...], str] | None = None,
    ) -> None:
        """Initialize the runner with the given state."""
        self.state = state
        self.last_events: list[MainEvent] = []
        self.all_events: list[MainEvent] = []
        self.dynamic_menus = dynamic_menus or dict(TEST_DYNAMIC_MENUS)
        self.path_mappings = path_mappings or dict(TEST_PATH_MAPPINGS)

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
        return compute_view_from_dynamic_menus(
            self.state,
            self.dynamic_menus,
            self.path_mappings,
        )

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
    """Create a ReducerRunner with initialized state and test dynamic menus.

    Usage::

        def test_something(nav: ReducerRunner):
            nav.dispatch(StackPushMenuAction(menu_key='main'))
            assert isinstance(nav.view, MenuViewData)
    """
    result = reducer(None, InitAction())
    assert isinstance(result, MainState)
    return ReducerRunner(result)


# Imported at module (collection) time on purpose: the runner's dispatch does
# `isinstance(action, MainAction)`, so it must share the same import
# generation as the test modules that construct the actions. A lazy in-fixture
# import would re-import a fresh module graph after an `app_context` test's
# sys.modules cleanup and silently turn every dispatch into a no-op. Placed
# down here rather than in the top import block because `event_runner` itself
# imports `ReducerRunner`/`reducer` back from this module — the names above
# must exist before the circular import resolves.
from tests.navigation.event_runner import NavigationEventRunner  # noqa: E402


@pytest.fixture
def navigation_events() -> Iterator[NavigationEventRunner]:
    """Create a runner wired to production menu event handlers."""
    from ubo_app.store.core.action_registry import (
        get_action,
        register_action,
        unregister_action,
    )

    result = reducer(None, InitAction())
    assert isinstance(result, MainState)
    runner = NavigationEventRunner(result)

    action_ids = {
        f'{MENU_NAVIGATE_PREFIX}{key}': key
        for key in ('main', 'apps', 'settings', 'notifications', 'power')
    }
    previous_handlers = {
        action_id: get_action(action_id)
        for action_id in action_ids
    }
    for action_id, menu_key in action_ids.items():
        def navigate(key: str = menu_key) -> None:
            runner.dispatch(StackPushMenuAction(menu_key=key))

        register_action(action_id, navigate, allow_reregister=True)

    yield runner

    for action_id, previous_handler in previous_handlers.items():
        if previous_handler is None:
            unregister_action(action_id)
        else:
            register_action(
                action_id,
                previous_handler,
                allow_reregister=True,
            )


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
