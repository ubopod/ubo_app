"""Test notification scrolling behavior with window/store snapshots.

Tests multi-page notifications (>3 items) with page scroll transitions,
and single-page notifications with text overflow slider scrolling.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from redux_pytest.fixtures import StoreSnapshot, WaitFor

    from tests.fixtures import (
        AppContext,
        Dispatcher,
        LoadServices,
        Stability,
    )
    from tests.fixtures.snapshot import WindowSnapshot
    from ubo_app.store.main import RootState


def _normalize_notifications(state: RootState) -> dict[str, Any]:
    """Select notification state with timestamps normalized for snapshots."""
    notifications_state = state.notifications
    normalized = [
        replace(n, timestamp=0, expiration_timestamp=None)
        for n in notifications_state.notifications
    ]
    return {
        'notifications': normalized,
        'unread_count': notifications_state.unread_count,
        'progress': notifications_state.progress,
    }


@pytest.mark.timeout(200)
async def test_multi_page_notification_scroll(
    app_context: AppContext,
    window_snapshot: WindowSnapshot,
    store_snapshot: StoreSnapshot[RootState],
    load_services: LoadServices,
    stability: Stability,
    wait_for: WaitFor,
    dispatcher: Dispatcher,
) -> None:
    """Test scrolling a multi-page notification with 5 items and long text."""
    from tenacity import wait_fixed

    from ubo_app.store.main import store
    from ubo_app.store.services.notifications import (
        Notification,
        NotificationActionItem,
        NotificationDisplayType,
        NotificationsAddAction,
    )

    app_context.set_app()
    unload_waiter = await load_services(
        ['keypad', 'notifications'],
        run_async=True,
    )

    @wait_for(run_async=True, wait=wait_fixed(1))
    def stack_is_loaded() -> None:
        state = store._state  # noqa: SLF001
        assert state is not None
        assert len(state.main.stack) > 0

    await stack_is_loaded()

    # Dispatch a notification with 6 action items + long text
    # 6 items + dismiss = 7 items → 3 pages (ceil(7/3) = 3)
    # Page 1: items 1-3, text at top, scrollbar at top
    # Page 2: items 4-6, text continued, scrollbar at middle
    # Page 3: dismiss only, remaining text, scrollbar at bottom
    long_text = (
        'This is a very long notification content that should exceed the '
        'visible area of the notification view. It contains multiple lines '
        'of text to test that text overflow and scrolling work correctly '
        'within the notification widget. The text continues across pages '
        'so the user can read the full message while also seeing the '
        'remaining action items on subsequent pages.'
    )

    notification = Notification(
        id='test-scroll-notification',
        title='Scroll Test',
        content=long_text,
        display_type=NotificationDisplayType.STICKY,
        show_dismiss_action=True,
        actions=[
            NotificationActionItem(
                key=f'action_{i}',
                icon=chr(0xF0000 + i),
                label=f'Action {i}',
                is_short=True,
            )
            for i in range(6)
        ],
    )

    store.dispatch(NotificationsAddAction(notification=notification))

    await stability(initial_wait=4)

    from ubo_app.store.services.keypad import Key

    # Page 1: text at top + first 3 items, scrollbar at top
    window_snapshot.take(title='page1')
    store_snapshot.take(selector=_normalize_notifications)

    # Scroll down to page 2
    await dispatcher.send_key(Key.DOWN)
    await stability(initial_wait=2)

    # Page 2: text continued + items 4-6, scrollbar at middle
    window_snapshot.take(title='page2')
    store_snapshot.take(selector=_normalize_notifications)

    # Scroll down to page 3
    await dispatcher.send_key(Key.DOWN)
    await stability(initial_wait=2)

    # Page 3: remaining text + dismiss only, scrollbar at bottom (end)
    window_snapshot.take(title='page3')
    store_snapshot.take(selector=_normalize_notifications)

    await unload_waiter()


@pytest.mark.timeout(200)
async def test_single_page_notification_text_scroll(
    app_context: AppContext,
    window_snapshot: WindowSnapshot,
    store_snapshot: StoreSnapshot[RootState],
    load_services: LoadServices,
    stability: Stability,
    wait_for: WaitFor,
    dispatcher: Dispatcher,
) -> None:
    """Test text scrolling on a single-page notification with overflow text."""
    from tenacity import wait_fixed

    from ubo_app.store.main import store
    from ubo_app.store.services.notifications import (
        Notification,
        NotificationActionItem,
        NotificationDisplayType,
        NotificationsAddAction,
    )

    app_context.set_app()
    unload_waiter = await load_services(
        ['keypad', 'notifications'],
        run_async=True,
    )

    @wait_for(run_async=True, wait=wait_fixed(1))
    def stack_is_loaded() -> None:
        state = store._state  # noqa: SLF001
        assert state is not None
        assert len(state.main.stack) > 0

    await stack_is_loaded()

    # Dispatch a notification with 2 items (+ dismiss = 3, single page)
    # and very long text that overflows
    long_text = (
        'This notification has a single page of items but the text content '
        'is long enough to exceed the visible area. The slider should appear '
        'on the right side and pressing UP/DOWN should scroll the text. '
        'This tests the ApplicationScrollEvent path in the reducer which '
        'triggers go_up/go_down on the notification widget to adjust the '
        'animated slider value for smooth text scrolling within the view.'
    )

    notification = Notification(
        id='test-text-scroll',
        title='Text Scroll Test Notification',
        content=long_text,
        display_type=NotificationDisplayType.STICKY,
        show_dismiss_action=True,
        actions=[
            NotificationActionItem(
                key=f'action_{i}',
                icon=chr(0xF0000 + i),
                label=f'Action {i}',
                is_short=True,
            )
            for i in range(2)
        ],
    )

    store.dispatch(NotificationsAddAction(notification=notification))

    await stability(initial_wait=4)

    # Initial view: text visible with slider
    window_snapshot.take(title='initial')
    store_snapshot.take(selector=_normalize_notifications)

    # Scroll down to move text
    from ubo_app.store.services.keypad import Key

    await dispatcher.send_key(Key.DOWN)
    await stability(initial_wait=2)

    # Text should have scrolled down
    window_snapshot.take(title='scrolled')
    store_snapshot.take(selector=_normalize_notifications)

    await unload_waiter()
