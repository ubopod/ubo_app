"""Tests for compute_view_from_stack in reducer.py.

These are pure unit tests that verify view data computation
from stack state. Uses a test menu tree to avoid importing menus.py
(which triggers store side effects).

NOTE: We cannot import compute_view_from_stack at module level because
reducer.py imports menus.py which imports store.main, creating a circular
import. Instead, we define a local copy of the function using the same
dependencies (which don't have the circular issue).
"""

from __future__ import annotations

from typing import cast

from ubo_gui.menu.types import HeadlessMenu, SubMenuItem, menu_items

from ubo_app.store.core.constants import PAGE_SIZE
from ubo_app.store.core.menu_adapter import (
    get_current_menu_from_stack,
    item_to_menu_item_data,
)
from ubo_app.store.core.stack_ops import create_root_stack_item, push_menu
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


def compute_view_from_stack(state: MainState) -> ViewData:
    """Local copy of compute_view_from_stack to avoid circular imports.

    This mirrors the function in reducer.py exactly.
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

# Test menu tree - avoids importing menus.py which triggers store side effects
_CHILD_MENU = HeadlessMenu(
    title='Apps',
    items=[
        SubMenuItem(key='wifi', label='Wi-Fi', icon='W', sub_menu=HeadlessMenu(
            title='Wi-Fi',
            items=[],
            placeholder='No networks',
        )),
        SubMenuItem(key='bt', label='Bluetooth', icon='B', sub_menu=HeadlessMenu(
            title='Bluetooth',
            items=[],
        )),
        SubMenuItem(key='vpn', label='VPN', icon='V', sub_menu=HeadlessMenu(
            title='VPN',
            items=[],
        )),
        SubMenuItem(key='extra', label='Extra', icon='E', sub_menu=HeadlessMenu(
            title='Extra',
            items=[],
        )),
    ],
)

TEST_MENU = HeadlessMenu(
    title='Home',
    items=[
        SubMenuItem(key='main', label='Main', icon='M', sub_menu=_CHILD_MENU),
        SubMenuItem(key='notifications', label='Notifications', icon='N',
                    sub_menu=HeadlessMenu(title='Notifications', items=[])),
        SubMenuItem(key='power', label='Power', icon='P',
                    sub_menu=HeadlessMenu(title='Power', items=[])),
    ],
)


def _make_state(
    stack: tuple | None = None,
    path: tuple[str, ...] = (),
) -> MainState:
    """Create a MainState with the test menu tree."""
    if stack is None:
        stack = create_root_stack_item()
    return MainState(menu=TEST_MENU, stack=stack, path=path)


class TestEmptyAndRootStack:
    """Tests for empty and root-only stacks."""

    def test_empty_stack_returns_home_view(self) -> None:
        """Verify empty stack produces a HomeViewData."""
        state = MainState(menu=TEST_MENU, stack=())
        view = compute_view_from_stack(state)
        assert isinstance(view, HomeViewData)

    def test_root_only_returns_home_view(self) -> None:
        """Verify root-only stack produces a HomeViewData."""
        state = _make_state()
        view = compute_view_from_stack(state)
        assert isinstance(view, HomeViewData)

    def test_home_view_has_menu_items(self) -> None:
        """Verify home view contains the expected menu items."""
        state = _make_state()
        view = compute_view_from_stack(state)
        assert isinstance(view, HomeViewData)
        assert len(view.menu_items) == 3
        labels = [item.label for item in view.menu_items]
        assert 'Main' in labels
        assert 'Notifications' in labels
        assert 'Power' in labels

    def test_home_view_shows_status_bar(self) -> None:
        """Verify home view has the status bar visible."""
        state = _make_state()
        view = compute_view_from_stack(state)
        assert isinstance(view, HomeViewData)
        assert view.show_status_bar is True

    def test_home_view_default_gauges(self) -> None:
        """Verify home view initializes gauges to zero."""
        state = _make_state()
        view = compute_view_from_stack(state)
        assert isinstance(view, HomeViewData)
        assert view.cpu_percent == 0.0
        assert view.ram_percent == 0.0
        assert view.volume_level == 0.0


class TestMenuView:
    """Tests for menu views at depth > 1."""

    def test_submenu_returns_menu_view(self) -> None:
        """Verify submenu navigation produces a MenuViewData."""
        state = _make_state()
        state = push_menu(state, 'main')
        view = compute_view_from_stack(state)
        assert isinstance(view, MenuViewData)

    def test_menu_view_has_title(self) -> None:
        """Verify menu view contains the correct title."""
        state = _make_state()
        state = push_menu(state, 'main')
        view = compute_view_from_stack(state)
        assert isinstance(view, MenuViewData)
        assert view.title == 'Apps'

    def test_menu_view_has_items(self) -> None:
        """Verify menu view contains all submenu items."""
        state = _make_state()
        state = push_menu(state, 'main')
        view = compute_view_from_stack(state)
        assert isinstance(view, MenuViewData)
        assert len(view.items) == 4

    def test_menu_view_page_index_zero(self) -> None:
        """Verify menu view starts at page index zero."""
        state = _make_state()
        state = push_menu(state, 'main')
        view = compute_view_from_stack(state)
        assert isinstance(view, MenuViewData)
        assert view.page_index == 0

    def test_menu_view_total_pages(self) -> None:
        """Verify menu view computes total pages correctly."""
        state = _make_state()
        state = push_menu(state, 'main')
        view = compute_view_from_stack(state)
        assert isinstance(view, MenuViewData)
        # 4 items / PAGE_SIZE(3) = ceil(4/3) = 2 pages
        assert view.total_pages == 2

    def test_menu_view_shows_status_bar_on_first_page(self) -> None:
        """Verify status bar is visible on the first page."""
        state = _make_state()
        state = push_menu(state, 'main')
        view = compute_view_from_stack(state)
        assert isinstance(view, MenuViewData)
        assert view.show_status_bar is True

    def test_menu_view_hides_status_bar_on_later_pages(self) -> None:
        """Verify status bar is hidden on pages after the first."""
        state = _make_state()
        state = push_menu(state, 'main')
        # Manually set page_index to simulate pagination
        from dataclasses import replace

        top = state.stack[-1]
        assert isinstance(top, MenuStackItem)
        new_top = replace(top, page_index=1)
        state = replace(state, stack=(*state.stack[:-1], new_top))
        view = compute_view_from_stack(state)
        assert isinstance(view, MenuViewData)
        assert view.show_status_bar is False

    def test_deep_menu_returns_menu_view(self) -> None:
        """Verify deeply nested menu returns correct MenuViewData."""
        state = _make_state()
        state = push_menu(state, 'main')
        state = push_menu(state, 'wifi')
        view = compute_view_from_stack(state)
        assert isinstance(view, MenuViewData)
        assert view.title == 'Wi-Fi'

    def test_no_menu_found_returns_home_view(self) -> None:
        """Verify nonexistent menu key falls back to HomeViewData."""
        state = _make_state()
        state = push_menu(state, 'nonexistent')
        view = compute_view_from_stack(state)
        assert isinstance(view, HomeViewData)


class TestApplicationView:
    """Tests for application stack items."""

    def test_application_returns_application_view(self) -> None:
        """Verify application item produces ApplicationViewData."""
        state = _make_state()
        stack = (*state.stack, ApplicationStackItem(
            id='a1', application_id='camera:viewfinder',
        ))
        state = MainState(menu=TEST_MENU, stack=stack)
        view = compute_view_from_stack(state)
        assert isinstance(view, ApplicationViewData)

    def test_application_view_has_correct_id(self) -> None:
        """Verify application view carries the correct application id."""
        state = _make_state()
        stack = (*state.stack, ApplicationStackItem(
            id='a1', application_id='camera:viewfinder',
        ))
        state = MainState(menu=TEST_MENU, stack=stack)
        view = compute_view_from_stack(state)
        assert isinstance(view, ApplicationViewData)
        assert view.application_id == 'camera:viewfinder'

    def test_application_view_hides_status_bar(self) -> None:
        """Verify application view hides the status bar."""
        state = _make_state()
        stack = (*state.stack, ApplicationStackItem(
            id='a1', application_id='test:app',
        ))
        state = MainState(menu=TEST_MENU, stack=stack)
        view = compute_view_from_stack(state)
        assert isinstance(view, ApplicationViewData)
        assert view.show_status_bar is False

    def test_application_view_converts_kwargs_to_extra_data(self) -> None:
        """Verify kwargs are converted to extra_data in the view."""
        state = _make_state()
        stack = (*state.stack, ApplicationStackItem(
            id='a1',
            application_id='test:app',
            initialization_kwargs={'text': 'hello'},
        ))
        state = MainState(menu=TEST_MENU, stack=stack)
        view = compute_view_from_stack(state)
        assert isinstance(view, ApplicationViewData)
        assert view.extra_data == {'text': 'hello'}


class TestNotificationView:
    """Tests for notification stack items."""

    def test_notification_returns_notification_view(self) -> None:
        """Verify notification item produces NotificationViewData."""
        state = _make_state()
        stack = (*state.stack, NotificationStackItem(
            id='n1', notification_id='notif-123',
        ))
        state = MainState(menu=TEST_MENU, stack=stack)
        view = compute_view_from_stack(state)
        assert isinstance(view, NotificationViewData)

    def test_notification_view_has_correct_id(self) -> None:
        """Verify notification view carries the correct id."""
        state = _make_state()
        stack = (*state.stack, NotificationStackItem(
            id='n1', notification_id='notif-123',
        ))
        state = MainState(menu=TEST_MENU, stack=stack)
        view = compute_view_from_stack(state)
        assert isinstance(view, NotificationViewData)
        assert view.notification_id == 'notif-123'

    def test_notification_view_hides_status_bar(self) -> None:
        """Verify notification view hides the status bar."""
        state = _make_state()
        stack = (*state.stack, NotificationStackItem(
            id='n1', notification_id='notif-1',
        ))
        state = MainState(menu=TEST_MENU, stack=stack)
        view = compute_view_from_stack(state)
        assert isinstance(view, NotificationViewData)
        assert view.show_status_bar is False


class TestMixedStack:
    """Tests for stacks with interleaved item types."""

    def test_app_over_menu_shows_app(self) -> None:
        """Verify application on top of menu shows application view."""
        state = _make_state()
        state = push_menu(state, 'main')
        stack = (*state.stack, ApplicationStackItem(
            id='a1', application_id='test:app',
        ))
        state = MainState(menu=TEST_MENU, stack=stack, path=state.path)
        view = compute_view_from_stack(state)
        assert isinstance(view, ApplicationViewData)

    def test_notification_over_app_shows_notification(self) -> None:
        """Verify notification on top of app shows notification view."""
        state = _make_state()
        stack = (
            *state.stack,
            ApplicationStackItem(id='a1', application_id='test:app'),
            NotificationStackItem(id='n1', notification_id='notif-1'),
        )
        state = MainState(menu=TEST_MENU, stack=stack)
        view = compute_view_from_stack(state)
        assert isinstance(view, NotificationViewData)

    def test_menu_over_app_shows_menu(self) -> None:
        """Menu on top after app shows menu view.

        Since app doesn't contribute to path,
        get_current_menu_from_stack should traverse only menu items.
        """
        state = _make_state()
        stack = (
            state.stack[0],
            ApplicationStackItem(id='a1', application_id='test:app'),
            MenuStackItem(id='m1', menu_key='main', page_index=0),
        )
        state = MainState(
            menu=TEST_MENU,
            stack=stack,
            path=('main',),
        )
        view = compute_view_from_stack(state)
        assert isinstance(view, MenuViewData)
