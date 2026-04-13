"""Tests for view computation from stack state.

These are pure unit tests that verify view data computation
from stack state using dynamic menus instead of the legacy menu tree.
"""

from __future__ import annotations

from dataclasses import replace

from ubo_app.store.core.constants import MENU_NAVIGATE_PREFIX, compute_total_pages
from ubo_app.store.core.stack_ops import create_root_stack_item, push_menu
from ubo_app.store.core.types import (
    ApplicationStackItem,
    ApplicationViewData,
    DynamicMenuData,
    HomeViewData,
    MainState,
    MenuItemData,
    MenuStackItem,
    MenuViewData,
    NotificationStackItem,
    NotificationViewData,
    RenderStackItem,
    RenderViewData,
    ViewData,
)

# Test dynamic menus (replaces legacy menu tree)
TEST_DYNAMIC_MENUS: dict[str, DynamicMenuData] = {
    'home:main': DynamicMenuData(
        menu_id='home:main',
        title='Home',
        items=(
            MenuItemData(
                key='main', label='Main', icon='M', is_short=True,
                action_id=f'{MENU_NAVIGATE_PREFIX}main',
            ),
            MenuItemData(
                key='notifications', label='Notifications', icon='N',
                is_short=True, action_id=f'{MENU_NAVIGATE_PREFIX}notifications',
            ),
            MenuItemData(
                key='power', label='Power', icon='P', is_short=True,
                action_id=f'{MENU_NAVIGATE_PREFIX}power',
            ),
        ),
    ),
    'main:menu': DynamicMenuData(
        menu_id='main:menu',
        title='Main',
        items=(
            MenuItemData(
                key='item_a', label='Item A', icon='A',
                action_id=f'{MENU_NAVIGATE_PREFIX}item_a',
            ),
            MenuItemData(
                key='item_b', label='Item B', icon='B',
                action_id=f'{MENU_NAVIGATE_PREFIX}item_b',
            ),
            MenuItemData(
                key='item_c', label='Item C', icon='C',
                action_id=f'{MENU_NAVIGATE_PREFIX}item_c',
            ),
            MenuItemData(
                key='item_d', label='Item D', icon='D',
                action_id=f'{MENU_NAVIGATE_PREFIX}item_d',
            ),
        ),
    ),
    'sub:list': DynamicMenuData(
        menu_id='sub:list',
        title='Sub Menu',
        items=(),
        placeholder='No items',
    ),
}

TEST_PATH_MAPPINGS: dict[tuple[str, ...], str] = {
    ('main',): 'main:menu',
    ('main', 'item_a'): 'sub:list',
}


def compute_view_from_dynamic_menus(  # noqa: C901
    state: MainState,
    dynamic_menus: dict[str, DynamicMenuData] | None = None,
    path_mappings: dict[tuple[str, ...], str] | None = None,
) -> ViewData:
    """Compute view data from dynamic menus."""
    if dynamic_menus is None:
        dynamic_menus = TEST_DYNAMIC_MENUS
    if path_mappings is None:
        path_mappings = TEST_PATH_MAPPINGS

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

    if isinstance(top_item, NotificationStackItem):
        return NotificationViewData(
            notification_id=top_item.notification_id,
            show_status_bar=False,
        )

    if not isinstance(top_item, MenuStackItem):
        return HomeViewData()

    depth = len([i for i in stack if isinstance(i, MenuStackItem)])
    if depth <= 1:
        home_menu = dynamic_menus.get('home:main')
        home_items = home_menu.items if home_menu else ()
        return HomeViewData(
            show_status_bar=True,
            menu_items=tuple(item for item in home_items if item is not None),
            cpu_percent=50.0,
            ram_percent=50.0,
            volume_level=0.0,
        )

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

    return HomeViewData()


def _make_state(
    stack: tuple | None = None,
    path: tuple[str, ...] = (),
) -> MainState:
    """Create a MainState for testing."""
    if stack is None:
        stack = create_root_stack_item()
    return MainState(stack=stack, path=path)


class TestEmptyAndRootStack:
    """Tests for empty and root-only stacks."""

    def test_empty_stack_returns_home_view(self) -> None:
        """Verify empty stack produces a HomeViewData."""
        state = MainState(stack=())
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, HomeViewData)

    def test_root_only_returns_home_view(self) -> None:
        """Verify root-only stack produces a HomeViewData."""
        state = _make_state()
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, HomeViewData)

    def test_home_view_has_menu_items(self) -> None:
        """Verify home view contains the expected menu items."""
        state = _make_state()
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, HomeViewData)
        assert len(view.menu_items) == 3
        labels = [item.label for item in view.menu_items]
        assert 'Main' in labels
        assert 'Notifications' in labels
        assert 'Power' in labels

    def test_home_view_shows_status_bar(self) -> None:
        """Verify home view has the status bar visible."""
        state = _make_state()
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, HomeViewData)
        assert view.show_status_bar is True

    def test_home_view_default_gauges(self) -> None:
        """Verify home view initializes gauges to 50% when no providers registered."""
        state = _make_state()
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, HomeViewData)
        assert view.cpu_percent == 50.0
        assert view.ram_percent == 50.0
        assert view.volume_level == 0.0


class TestMenuView:
    """Tests for menu views at depth > 1."""

    def test_submenu_returns_menu_view(self) -> None:
        """Verify submenu navigation produces a MenuViewData."""
        state = _make_state()
        state = push_menu(state, 'main')
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, MenuViewData)

    def test_menu_view_has_title(self) -> None:
        """Verify menu view contains the correct title."""
        state = _make_state()
        state = push_menu(state, 'main')
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, MenuViewData)
        assert view.title == 'Main'

    def test_menu_view_has_items(self) -> None:
        """Verify menu view contains all submenu items."""
        state = _make_state()
        state = push_menu(state, 'main')
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, MenuViewData)
        assert len(view.items) == 4

    def test_menu_view_page_index_zero(self) -> None:
        """Verify menu view starts at page index zero."""
        state = _make_state()
        state = push_menu(state, 'main')
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, MenuViewData)
        assert view.page_index == 0

    def test_menu_view_total_pages(self) -> None:
        """Verify menu view computes total pages correctly."""
        state = _make_state()
        state = push_menu(state, 'main')
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, MenuViewData)
        # 4 items / PAGE_SIZE(3) = ceil(4/3) = 2 pages
        assert view.total_pages == 2

    def test_menu_view_shows_status_bar_on_first_page(self) -> None:
        """Verify status bar is visible on the first page."""
        state = _make_state()
        state = push_menu(state, 'main')
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, MenuViewData)
        assert view.show_status_bar is True

    def test_menu_view_hides_status_bar_on_later_pages(self) -> None:
        """Verify status bar is hidden on pages after the first."""
        state = _make_state()
        state = push_menu(state, 'main')
        top = state.stack[-1]
        assert isinstance(top, MenuStackItem)
        new_top = replace(top, page_index=1)
        state = replace(state, stack=(*state.stack[:-1], new_top))
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, MenuViewData)
        assert view.show_status_bar is False

    def test_deep_menu_returns_menu_view(self) -> None:
        """Verify deeply nested menu returns correct MenuViewData."""
        state = _make_state()
        state = push_menu(state, 'main')
        state = push_menu(state, 'item_a')
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, MenuViewData)
        assert view.title == 'Sub Menu'

    def test_no_menu_found_returns_home_view(self) -> None:
        """Verify nonexistent menu key falls back to HomeViewData."""
        state = _make_state()
        state = push_menu(state, 'nonexistent')
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, HomeViewData)


class TestApplicationView:
    """Tests for application stack items."""

    def test_application_returns_application_view(self) -> None:
        """Verify application item produces ApplicationViewData."""
        state = _make_state()
        stack = (
            *state.stack,
            ApplicationStackItem(id='a1', application_id='test:custom-widget'),
        )
        state = MainState(stack=stack)
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, ApplicationViewData)

    def test_application_view_has_correct_id(self) -> None:
        """Verify application view carries the correct application id."""
        state = _make_state()
        stack = (
            *state.stack,
            ApplicationStackItem(id='a1', application_id='test:custom-widget'),
        )
        state = MainState(stack=stack)
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, ApplicationViewData)
        assert view.application_id == 'test:custom-widget'

    def test_application_view_hides_status_bar(self) -> None:
        """Verify application view hides the status bar."""
        state = _make_state()
        stack = (
            *state.stack,
            ApplicationStackItem(id='a1', application_id='test:app'),
        )
        state = MainState(stack=stack)
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, ApplicationViewData)
        assert view.show_status_bar is False

    def test_application_view_converts_kwargs_to_extra_data(self) -> None:
        """Verify kwargs are converted to extra_data in the view."""
        state = _make_state()
        stack = (
            *state.stack,
            ApplicationStackItem(
                id='a1',
                application_id='test:app',
                initialization_kwargs={'text': 'hello'},
            ),
        )
        state = MainState(stack=stack)
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, ApplicationViewData)
        assert view.extra_data == {'text': 'hello'}


class TestRenderView:
    """Tests for render stack items."""

    def test_render_returns_render_view(self) -> None:
        """Verify render item produces RenderViewData."""
        state = _make_state()
        stack = (
            *state.stack,
            RenderStackItem(id='r1', kind='qr_code'),
        )
        state = MainState(stack=stack)
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, RenderViewData)

    def test_render_view_has_correct_kind(self) -> None:
        """Verify render view carries the correct kind."""
        state = _make_state()
        stack = (
            *state.stack,
            RenderStackItem(id='r1', kind='text_viewer', title='My Text'),
        )
        state = MainState(stack=stack)
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, RenderViewData)
        assert view.kind == 'text_viewer'
        assert view.title == 'My Text'

    def test_render_view_hides_status_bar(self) -> None:
        """Verify render view hides the status bar."""
        state = _make_state()
        stack = (
            *state.stack,
            RenderStackItem(id='r1', kind='status'),
        )
        state = MainState(stack=stack)
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, RenderViewData)
        assert view.show_status_bar is False

    def test_render_view_preserves_props(self) -> None:
        """Verify render view carries props from stack item."""
        state = _make_state()
        stack = (
            *state.stack,
            RenderStackItem(
                id='r1',
                kind='qr_code',
                props={'value': 'https://example.com', 'label': 'Example'},
            ),
        )
        state = MainState(stack=stack)
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, RenderViewData)
        assert view.props['value'] == 'https://example.com'
        assert view.props['label'] == 'Example'

    def test_render_view_preserves_stream_id(self) -> None:
        """Verify render view carries stream_id from stack item."""
        state = _make_state()
        stack = (
            *state.stack,
            RenderStackItem(
                id='r1',
                kind='frame_stream',
                stream_id='camera:viewfinder',
            ),
        )
        state = MainState(stack=stack)
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, RenderViewData)
        assert view.stream_id == 'camera:viewfinder'


class TestNotificationView:
    """Tests for notification stack items."""

    def test_notification_returns_notification_view(self) -> None:
        """Verify notification item produces NotificationViewData."""
        state = _make_state()
        stack = (
            *state.stack,
            NotificationStackItem(id='n1', notification_id='notif-123'),
        )
        state = MainState(stack=stack)
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, NotificationViewData)

    def test_notification_view_has_correct_id(self) -> None:
        """Verify notification view carries the correct id."""
        state = _make_state()
        stack = (
            *state.stack,
            NotificationStackItem(id='n1', notification_id='notif-123'),
        )
        state = MainState(stack=stack)
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, NotificationViewData)
        assert view.notification_id == 'notif-123'

    def test_notification_view_hides_status_bar(self) -> None:
        """Verify notification view hides the status bar."""
        state = _make_state()
        stack = (
            *state.stack,
            NotificationStackItem(id='n1', notification_id='notif-1'),
        )
        state = MainState(stack=stack)
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, NotificationViewData)
        assert view.show_status_bar is False


class TestMixedStack:
    """Tests for stacks with interleaved item types."""

    def test_app_over_menu_shows_app(self) -> None:
        """Verify application on top of menu shows application view."""
        state = _make_state()
        state = push_menu(state, 'main')
        stack = (
            *state.stack,
            ApplicationStackItem(id='a1', application_id='test:app'),
        )
        state = MainState(stack=stack, path=state.path)
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, ApplicationViewData)

    def test_notification_over_app_shows_notification(self) -> None:
        """Verify notification on top of app shows notification view."""
        state = _make_state()
        stack = (
            *state.stack,
            ApplicationStackItem(id='a1', application_id='test:app'),
            NotificationStackItem(id='n1', notification_id='notif-1'),
        )
        state = MainState(stack=stack)
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, NotificationViewData)

    def test_menu_over_app_shows_menu(self) -> None:
        """Menu on top after app shows menu view."""
        state = _make_state()
        stack = (
            state.stack[0],
            ApplicationStackItem(id='a1', application_id='test:app'),
            MenuStackItem(id='m1', menu_key='main', page_index=0),
        )
        state = MainState(
            stack=stack,
            path=('main',),
        )
        view = compute_view_from_dynamic_menus(state)
        assert isinstance(view, MenuViewData)
