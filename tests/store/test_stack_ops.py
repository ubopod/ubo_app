"""Tests for stack manipulation functions in stack_ops.py.

These are pure unit tests that test each function directly.
No store, Kivy, or service imports needed.
"""

from __future__ import annotations

from ubo_app.store.core.stack_ops import (
    create_root_stack_item,
    derive_path_from_stack,
    pop_item,
    pop_notification,
    pop_stack,
    pop_to_root,
    push_application,
    push_menu,
    push_notification,
    push_render,
    set_page_index,
)
from ubo_app.store.core.types import (
    ApplicationStackItem,
    MainState,
    MenuStackItem,
    NotificationStackItem,
    RenderStackItem,
)


def _make_state(
    stack: tuple | None = None,
    path: tuple[str, ...] = (),
) -> MainState:
    """Create a MainState with the given stack for testing."""
    if stack is None:
        stack = create_root_stack_item()
    return MainState(stack=stack, path=path)


class TestCreateRootStackItem:
    """Tests for create_root_stack_item."""

    def test_returns_single_item_tuple(self) -> None:
        """Verify root stack item is a single-element tuple."""
        result = create_root_stack_item()
        assert len(result) == 1

    def test_root_has_empty_key(self) -> None:
        """Verify root stack item has an empty menu key."""
        (root,) = create_root_stack_item()
        assert root.menu_key == ''

    def test_root_has_page_index_zero(self) -> None:
        """Verify root stack item starts at page index zero."""
        (root,) = create_root_stack_item()
        assert root.page_index == 0

    def test_root_has_unique_id(self) -> None:
        """Verify each root stack item gets a unique id."""
        (root1,) = create_root_stack_item()
        (root2,) = create_root_stack_item()
        assert root1.id != root2.id

    def test_root_is_menu_stack_item(self) -> None:
        """Verify root stack item is a MenuStackItem."""
        (root,) = create_root_stack_item()
        assert isinstance(root, MenuStackItem)


class TestDerivePathFromStack:
    """Tests for derive_path_from_stack (via the real import)."""

    def test_empty_stack(self) -> None:
        """Verify empty stack produces an empty path."""
        assert derive_path_from_stack(()) == ()

    def test_root_only(self) -> None:
        """Verify root-only stack produces an empty path."""
        root = MenuStackItem(id='root', menu_key='', page_index=0)
        assert derive_path_from_stack((root,)) == ()

    def test_single_menu_after_root(self) -> None:
        """Verify single menu item after root produces one-element path."""
        root = MenuStackItem(id='root', menu_key='', page_index=0)
        main = MenuStackItem(id='main', menu_key='main', page_index=0)
        assert derive_path_from_stack((root, main)) == ('main',)

    def test_deep_menu_path(self) -> None:
        """Verify deeply nested menus produce a multi-element path."""
        stack = (
            MenuStackItem(id='root', menu_key='', page_index=0),
            MenuStackItem(id='m', menu_key='main', page_index=0),
            MenuStackItem(id='s', menu_key='settings', page_index=0),
            MenuStackItem(id='n', menu_key='network', page_index=0),
        )
        assert derive_path_from_stack(stack) == ('main', 'settings', 'network')

    def test_skips_application_items(self) -> None:
        """Verify application items are excluded from the path."""
        stack = (
            MenuStackItem(id='root', menu_key='', page_index=0),
            MenuStackItem(id='m', menu_key='main', page_index=0),
            ApplicationStackItem(id='app', application_id='test:app'),
        )
        assert derive_path_from_stack(stack) == ('main',)

    def test_skips_notification_items(self) -> None:
        """Verify notification items are excluded from the path."""
        stack = (
            MenuStackItem(id='root', menu_key='', page_index=0),
            MenuStackItem(id='m', menu_key='main', page_index=0),
            NotificationStackItem(id='n', notification_id='notif1'),
        )
        assert derive_path_from_stack(stack) == ('main',)

    def test_mixed_stack_extracts_menu_keys_only(self) -> None:
        """Verify only menu keys are extracted from a mixed stack."""
        stack = (
            MenuStackItem(id='root', menu_key='', page_index=0),
            MenuStackItem(id='m', menu_key='main', page_index=0),
            ApplicationStackItem(id='a', application_id='app1'),
            MenuStackItem(id='s', menu_key='sub', page_index=0),
            NotificationStackItem(id='n', notification_id='n1'),
        )
        assert derive_path_from_stack(stack) == ('main', 'sub')


class TestPushMenu:
    """Tests for push_menu."""

    def test_appends_menu_stack_item(self) -> None:
        """Verify push_menu appends a MenuStackItem to the stack."""
        state = _make_state()
        new_state = push_menu(state, 'main')
        assert len(new_state.stack) == 2
        assert isinstance(new_state.stack[-1], MenuStackItem)
        assert new_state.stack[-1].menu_key == 'main'

    def test_updates_path(self) -> None:
        """Verify push_menu updates the path with the new key."""
        state = _make_state()
        new_state = push_menu(state, 'main')
        assert new_state.path == ('main',)

    def test_preserves_existing_stack(self) -> None:
        """Verify push_menu preserves existing stack items."""
        state = _make_state()
        original_root = state.stack[0]
        new_state = push_menu(state, 'main')
        assert new_state.stack[0] is original_root

    def test_new_item_has_page_index_zero(self) -> None:
        """Verify pushed menu item starts at page index zero."""
        state = _make_state()
        new_state = push_menu(state, 'main')
        item = new_state.stack[-1]
        assert isinstance(item, MenuStackItem)
        assert item.page_index == 0

    def test_new_item_has_unique_id(self) -> None:
        """Verify each pushed menu item gets a unique id."""
        state = _make_state()
        s1 = push_menu(state, 'main')
        s2 = push_menu(state, 'main')
        assert s1.stack[-1].id != s2.stack[-1].id

    def test_double_push_builds_path(self) -> None:
        """Verify two successive pushes build a two-element path."""
        state = _make_state()
        state = push_menu(state, 'main')
        state = push_menu(state, 'settings')
        assert state.path == ('main', 'settings')
        assert len(state.stack) == 3

    def test_does_not_mutate_original(self) -> None:
        """Verify push_menu does not mutate the original state."""
        state = _make_state()
        original_stack = state.stack
        push_menu(state, 'main')
        assert state.stack is original_stack


class TestPushApplication:
    """Tests for push_application."""

    def test_appends_application_stack_item(self) -> None:
        """Verify push_application appends an ApplicationStackItem."""
        state = _make_state()
        new_state = push_application(state, 'test:custom-widget')
        assert len(new_state.stack) == 2
        assert isinstance(new_state.stack[-1], ApplicationStackItem)
        assert new_state.stack[-1].application_id == 'test:custom-widget'

    def test_path_unchanged(self) -> None:
        """Verify push_application does not change the path."""
        state = _make_state()
        state = push_menu(state, 'main')
        original_path = state.path
        new_state = push_application(state, 'test:app')
        assert new_state.path == original_path

    def test_preserves_args(self) -> None:
        """Verify initialization args and kwargs are preserved."""
        state = _make_state()
        new_state = push_application(
            state,
            'test:app',
            initialization_args=('a', 'b'),
            initialization_kwargs={'key': 'val'},
        )
        item = new_state.stack[-1]
        assert isinstance(item, ApplicationStackItem)
        assert item.initialization_args == ('a', 'b')
        assert item.initialization_kwargs == {'key': 'val'}

    def test_default_args_are_empty(self) -> None:
        """Verify default args and kwargs are empty."""
        state = _make_state()
        new_state = push_application(state, 'test:app')
        item = new_state.stack[-1]
        assert isinstance(item, ApplicationStackItem)
        assert item.initialization_args == ()
        assert item.initialization_kwargs == {}

    def test_none_kwargs_becomes_empty_dict(self) -> None:
        """Verify None kwargs is normalized to an empty dict."""
        state = _make_state()
        new_state = push_application(state, 'test:app', initialization_kwargs=None)
        item = new_state.stack[-1]
        assert isinstance(item, ApplicationStackItem)
        assert item.initialization_kwargs == {}


class TestPushRender:
    """Tests for push_render."""

    def test_appends_render_stack_item(self) -> None:
        """Verify push_render appends a RenderStackItem."""
        state = _make_state()
        new_state = push_render(state, 'qr_code')
        assert len(new_state.stack) == 2
        assert isinstance(new_state.stack[-1], RenderStackItem)
        assert new_state.stack[-1].kind == 'qr_code'

    def test_preserves_props(self) -> None:
        """Verify push_render preserves props."""
        state = _make_state()
        new_state = push_render(
            state,
            'qr_code',
            props={'value': 'https://example.com', 'label': 'Example'},
        )
        item = new_state.stack[-1]
        assert isinstance(item, RenderStackItem)
        assert item.props == {'value': 'https://example.com', 'label': 'Example'}

    def test_preserves_stream_id(self) -> None:
        """Verify push_render preserves stream_id."""
        state = _make_state()
        new_state = push_render(
            state,
            'frame_stream',
            stream_id='camera:viewfinder',
        )
        item = new_state.stack[-1]
        assert isinstance(item, RenderStackItem)
        assert item.stream_id == 'camera:viewfinder'

    def test_path_unchanged(self) -> None:
        """Verify push_render does not change the path."""
        state = _make_state()
        state = push_menu(state, 'main')
        original_path = state.path
        new_state = push_render(state, 'status')
        assert new_state.path == original_path

    def test_default_props_are_empty(self) -> None:
        """Verify default props, items, and stream_id are empty."""
        state = _make_state()
        new_state = push_render(state, 'text_viewer')
        item = new_state.stack[-1]
        assert isinstance(item, RenderStackItem)
        assert item.props == {}
        assert item.items == ()
        assert item.stream_id == ''
        assert item.title == ''


class TestPushNotification:
    """Tests for push_notification."""

    def test_appends_notification_stack_item(self) -> None:
        """Verify push_notification appends a NotificationStackItem."""
        state = _make_state()
        new_state = push_notification(state, 'notif-123')
        assert len(new_state.stack) == 2
        assert isinstance(new_state.stack[-1], NotificationStackItem)
        assert new_state.stack[-1].notification_id == 'notif-123'

    def test_path_unchanged(self) -> None:
        """Verify push_notification does not change the path."""
        state = _make_state()
        state = push_menu(state, 'main')
        original_path = state.path
        new_state = push_notification(state, 'notif-1')
        assert new_state.path == original_path

    def test_is_idempotent_for_same_notification_id(self) -> None:
        """Pushing an already-present notification id is a no-op.

        Guards the stale-read race: notification download flows fire
        many ``StackPushNotificationAction``s; the reducer must dedup so
        a notification never lands on the stack twice.
        """
        state = _make_state()
        once = push_notification(state, 'notif-1')
        twice = push_notification(once, 'notif-1')
        assert twice is once
        assert (
            sum(
                isinstance(item, NotificationStackItem)
                and item.notification_id == 'notif-1'
                for item in twice.stack
            )
            == 1
        )


class TestPopNotification:
    """Tests for pop_notification."""

    def test_removes_matching_notification(self) -> None:
        """Verify pop_notification removes the NotificationStackItem by id."""
        state = _make_state()
        state = push_notification(state, 'notif-1')
        new_state = pop_notification(state, 'notif-1')
        assert not any(
            isinstance(item, NotificationStackItem)
            and item.notification_id == 'notif-1'
            for item in new_state.stack
        )

    def test_noop_when_not_present(self) -> None:
        """Popping a notification that isn't on the stack is a no-op."""
        state = _make_state()
        state = push_menu(state, 'main')
        assert pop_notification(state, 'missing') is state

    def test_path_unchanged(self) -> None:
        """Verify pop_notification does not change the path."""
        state = _make_state()
        state = push_menu(state, 'main')
        original_path = state.path
        state = push_notification(state, 'notif-1')
        new_state = pop_notification(state, 'notif-1')
        assert new_state.path == original_path

    def test_leaves_other_items_intact(self) -> None:
        """Only the matching notification is removed; siblings stay."""
        state = _make_state()
        state = push_menu(state, 'main')
        state = push_notification(state, 'keep')
        state = push_notification(state, 'drop')
        new_state = pop_notification(state, 'drop')
        notification_ids = {
            item.notification_id
            for item in new_state.stack
            if isinstance(item, NotificationStackItem)
        }
        assert notification_ids == {'keep'}


class TestPopStack:
    """Tests for pop_stack."""

    def test_returns_none_at_root(self) -> None:
        """Verify pop_stack returns None when already at root."""
        state = _make_state()
        assert pop_stack(state) is None

    def test_pops_one_item(self) -> None:
        """Verify pop_stack removes one item from the stack."""
        state = _make_state()
        state = push_menu(state, 'main')
        result = pop_stack(state)
        assert result is not None
        assert len(result.stack) == 1

    def test_pops_multiple_items(self) -> None:
        """Verify pop_stack removes multiple items when count > 1."""
        state = _make_state()
        state = push_menu(state, 'main')
        state = push_menu(state, 'settings')
        state = push_menu(state, 'network')
        result = pop_stack(state, count=2)
        assert result is not None
        assert len(result.stack) == 2
        assert result.path == ('main',)

    def test_clamps_to_root(self) -> None:
        """Verify pop_stack clamps to root when count exceeds depth."""
        state = _make_state()
        state = push_menu(state, 'main')
        state = push_menu(state, 'settings')
        result = pop_stack(state, count=100)
        assert result is not None
        assert len(result.stack) == 1
        assert result.path == ()

    def test_updates_path_after_pop(self) -> None:
        """Verify pop_stack updates the path after popping."""
        state = _make_state()
        state = push_menu(state, 'main')
        state = push_menu(state, 'settings')
        result = pop_stack(state)
        assert result is not None
        assert result.path == ('main',)

    def test_pops_non_menu_item(self) -> None:
        """Verify pop_stack removes non-menu items correctly."""
        state = _make_state()
        state = push_menu(state, 'main')
        state = push_application(state, 'test:app')
        result = pop_stack(state)
        assert result is not None
        assert len(result.stack) == 2
        assert result.path == ('main',)

    def test_returns_none_with_single_root(self) -> None:
        """Verify pop_stack returns None with only root on stack."""
        state = _make_state()
        assert pop_stack(state, count=5) is None


class TestPopToRoot:
    """Tests for pop_to_root."""

    def test_returns_none_at_root(self) -> None:
        """Verify pop_to_root returns None when already at root."""
        state = _make_state()
        assert pop_to_root(state) is None

    def test_pops_to_root(self) -> None:
        """Verify pop_to_root removes all items except root."""
        state = _make_state()
        state = push_menu(state, 'main')
        state = push_menu(state, 'settings')
        state = push_application(state, 'app1')
        result = pop_to_root(state)
        assert result is not None
        assert len(result.stack) == 1
        assert result.path == ()

    def test_keeps_root_item(self) -> None:
        """Verify pop_to_root preserves the original root item."""
        state = _make_state()
        root = state.stack[0]
        state = push_menu(state, 'main')
        result = pop_to_root(state)
        assert result is not None
        assert result.stack[0] is root


class TestPopItem:
    """Tests for pop_item."""

    def test_returns_none_if_not_found(self) -> None:
        """Verify pop_item returns None when item id is not found."""
        state = _make_state()
        assert pop_item(state, 'nonexistent') is None

    def test_removes_specific_item(self) -> None:
        """Verify pop_item removes the item with the given id."""
        state = _make_state()
        state = push_menu(state, 'main')
        state = push_application(state, 'test:app')
        app_id = state.stack[-1].id
        result = pop_item(state, app_id)
        assert result is not None
        assert len(result.stack) == 2
        assert all(item.id != app_id for item in result.stack)

    def test_updates_path_after_removal(self) -> None:
        """Verify pop_item updates the path after removal."""
        state = _make_state()
        state = push_menu(state, 'main')
        state = push_menu(state, 'settings')
        settings_id = state.stack[-1].id
        result = pop_item(state, settings_id)
        assert result is not None
        assert result.path == ('main',)

    def test_preserves_order(self) -> None:
        """Verify pop_item preserves the order of remaining items."""
        state = _make_state()
        state = push_menu(state, 'main')
        state = push_application(state, 'app1')
        state = push_menu(state, 'settings')
        app_id = state.stack[2].id
        result = pop_item(state, app_id)
        assert result is not None
        assert len(result.stack) == 3
        assert isinstance(result.stack[0], MenuStackItem)
        assert isinstance(result.stack[1], MenuStackItem)
        assert isinstance(result.stack[2], MenuStackItem)

    def test_does_not_remove_root(self) -> None:
        """Verify pop_item can target the root item by id."""
        state = _make_state()
        root_id = state.stack[0].id
        result = pop_item(state, root_id)
        assert result is not None
        assert len(result.stack) == 0


class TestSetPageIndex:
    """Tests for set_page_index."""

    def test_updates_page_index_on_top_menu(self) -> None:
        """Verify set_page_index updates the top menu item's page."""
        state = _make_state()
        state = push_menu(state, 'main')
        result = set_page_index(state, 2)
        assert result is not None
        top = result.stack[-1]
        assert isinstance(top, MenuStackItem)
        assert top.page_index == 2

    def test_returns_none_for_empty_stack(self) -> None:
        """Verify set_page_index returns None for an empty stack."""
        state = MainState(stack=())
        assert set_page_index(state, 1) is None

    def test_returns_none_for_non_menu_top(self) -> None:
        """Verify set_page_index returns None when top is not a menu."""
        state = _make_state()
        state = push_application(state, 'test:app')
        assert set_page_index(state, 1) is None

    def test_does_not_modify_other_items(self) -> None:
        """Verify set_page_index leaves other stack items unchanged."""
        state = _make_state()
        state = push_menu(state, 'main')
        state = push_menu(state, 'settings')
        original_main = state.stack[1]
        result = set_page_index(state, 3)
        assert result is not None
        assert result.stack[1] is original_main

    def test_sets_root_page_index(self) -> None:
        """Verify set_page_index works on the root menu item."""
        state = _make_state()
        result = set_page_index(state, 1)
        assert result is not None
        top = result.stack[-1]
        assert isinstance(top, MenuStackItem)
        assert top.page_index == 1
