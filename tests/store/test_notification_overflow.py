"""Tests for notification action pagination.

Verifies that notifications with more actions than PAGE_SIZE (3) report
correct total_pages, and that the full item list is sent to the GUI
(the GUI handles per-page slicing and half-item peek rendering).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from ubo_app.store.core.constants import (
    NOTIFICATION_ACTION_PREFIX,
    NOTIFICATION_DISMISS_PREFIX,
    PAGE_SIZE,
)

if TYPE_CHECKING:
    from ubo_app.store.core.types import MenuItemData
    from ubo_app.store.main import RootState


def _make_notification(
    *,
    notification_id: str = 'test-notif',
    num_actions: int = 3,
    show_dismiss: bool = False,
    has_extra_info: bool = False,
) -> object:
    """Create a test notification with a given number of actions."""
    from ubo_app.store.services.notifications import (
        Notification,
        NotificationActionItem,
        NotificationDisplayType,
    )

    actions = [
        NotificationActionItem(
            key=f'action_{i}',
            label=f'Action {i}',
            icon=f'icon{i}',
            color='#ffffff',
        )
        for i in range(num_actions)
    ]

    extra_info = None
    if has_extra_info:
        from ubo_app.store.services.speech_synthesis import ReadableInformation

        extra_info = ReadableInformation(text='Extra info text')

    return Notification(
        id=notification_id,
        title='Test',
        content='Test notification',
        icon='T',
        display_type=NotificationDisplayType.STICKY,
        show_dismiss_action=show_dismiss,
        actions=actions,
        extra_information=extra_info,
    )


def _make_state_with_notification(
    notification: object,
) -> RootState:
    """Create a minimal RootState-like object for view computation."""
    from unittest.mock import MagicMock

    state = MagicMock()
    state.notifications.notifications = [notification]
    return cast('RootState', state)


def _get_real_items(
    items: tuple[MenuItemData | None, ...],
) -> list[MenuItemData]:
    """Filter out None padding from items."""
    return [i for i in items if i is not None]


class TestNotificationSinglePage:
    """Tests for notifications that fit within PAGE_SIZE."""

    def test_3_actions_single_page(self) -> None:
        """3 actions exactly fill PAGE_SIZE — 1 page, all items present."""
        notification = _make_notification(num_actions=3)
        state = _make_state_with_notification(notification)

        from ubo_app.store.core.view_computation import get_notification_view_data

        view = get_notification_view_data(state, 'test-notif')
        real = _get_real_items(view.items)

        assert len(real) == PAGE_SIZE
        assert view.total_pages == 1
        assert view.page_index == 0

    def test_2_actions_single_page(self) -> None:
        """2 actions — 1 page, full list sent (no None padding)."""
        notification = _make_notification(num_actions=2)
        state = _make_state_with_notification(notification)

        from ubo_app.store.core.view_computation import get_notification_view_data

        view = get_notification_view_data(state, 'test-notif')

        expected_count = 2
        assert len(view.items) == expected_count
        assert all(i is not None for i in view.items)
        assert view.total_pages == 1


class TestNotificationPagination:
    """Tests for notifications with more actions than PAGE_SIZE."""

    def test_4_actions_has_2_pages(self) -> None:
        """4 actions > PAGE_SIZE — 2 pages, full list sent."""
        notification = _make_notification(num_actions=4)
        state = _make_state_with_notification(notification)

        from ubo_app.store.core.view_computation import get_notification_view_data

        view = get_notification_view_data(state, 'test-notif', page_index=0)

        expected_pages = 2
        assert view.total_pages == expected_pages
        assert view.page_index == 0
        # Full item list is sent — GUI does slicing
        expected_items = 4
        assert len(view.items) == expected_items

    def test_full_item_list_sent(self) -> None:
        """All items are sent regardless of page — GUI handles slicing."""
        notification = _make_notification(num_actions=5)
        state = _make_state_with_notification(notification)

        from ubo_app.store.core.view_computation import get_notification_view_data

        view0 = get_notification_view_data(state, 'test-notif', page_index=0)
        view1 = get_notification_view_data(state, 'test-notif', page_index=1)

        # Both pages get the same full item list
        expected_items = 5
        assert len(view0.items) == expected_items
        assert len(view1.items) == expected_items
        # But page_index differs
        assert view0.page_index == 0
        assert view1.page_index == 1

    def test_action_ids_sequential(self) -> None:
        """All action IDs follow notification:action:{id}:{index} pattern."""
        notification = _make_notification(num_actions=5)
        state = _make_state_with_notification(notification)

        from ubo_app.store.core.view_computation import get_notification_view_data

        view = get_notification_view_data(state, 'test-notif')
        real = _get_real_items(view.items)

        for i, item in enumerate(real):
            expected = f'{NOTIFICATION_ACTION_PREFIX}test-notif:{i}'
            assert item.action_id == expected

    def test_6_actions_has_2_pages(self) -> None:
        """6 actions = exactly 2 full pages."""
        notification = _make_notification(num_actions=6)
        state = _make_state_with_notification(notification)

        from ubo_app.store.core.view_computation import get_notification_view_data

        view = get_notification_view_data(state, 'test-notif')

        expected_pages = 2
        assert view.total_pages == expected_pages
        expected_items = 6
        assert len(view.items) == expected_items

    def test_page_index_clamped(self) -> None:
        """Page index is clamped to max valid value."""
        notification = _make_notification(num_actions=4)
        state = _make_state_with_notification(notification)

        from ubo_app.store.core.view_computation import get_notification_view_data

        view = get_notification_view_data(state, 'test-notif', page_index=99)

        assert view.page_index == 1  # clamped to last page


class TestNotificationWithDismiss:
    """Tests for notifications with dismiss button and pagination."""

    def test_dismiss_takes_slot(self) -> None:
        """Dismiss button is included in item list."""
        notification = _make_notification(num_actions=2, show_dismiss=True)
        state = _make_state_with_notification(notification)

        from ubo_app.store.core.view_computation import get_notification_view_data

        view = get_notification_view_data(state, 'test-notif')
        real = _get_real_items(view.items)

        # 2 actions + 1 dismiss = 3
        assert len(real) == PAGE_SIZE
        assert view.total_pages == 1
        assert real[-1].action_id is not None
        assert real[-1].action_id.startswith(NOTIFICATION_DISMISS_PREFIX)

    def test_dismiss_with_pagination(self) -> None:
        """3 actions + dismiss = 4 items — 2 pages."""
        notification = _make_notification(num_actions=3, show_dismiss=True)
        state = _make_state_with_notification(notification)

        from ubo_app.store.core.view_computation import get_notification_view_data

        view = get_notification_view_data(state, 'test-notif')

        expected_pages = 2
        assert view.total_pages == expected_pages
        expected_items = 4
        assert len(view.items) == expected_items
        # Last item is dismiss
        real = _get_real_items(view.items)
        assert real[-1].action_id is not None
        assert real[-1].action_id.startswith(NOTIFICATION_DISMISS_PREFIX)


class TestNotificationActionIds:
    """Tests for correct action_id assignment."""

    @pytest.mark.parametrize('num_actions', [1, 2, 3])
    def test_action_ids_sequential(self, num_actions: int) -> None:
        """Action IDs follow notification:action:{id}:{index} pattern."""
        notification = _make_notification(num_actions=num_actions)
        state = _make_state_with_notification(notification)

        from ubo_app.store.core.view_computation import get_notification_view_data

        view = get_notification_view_data(state, 'test-notif')
        real = _get_real_items(view.items)

        for i, item in enumerate(real):
            expected = f'{NOTIFICATION_ACTION_PREFIX}test-notif:{i}'
            assert item.action_id == expected
