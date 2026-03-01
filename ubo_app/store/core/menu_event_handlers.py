"""Menu event handlers for the headless core.

In the headless (dumb UI) architecture, the core emits MenuChooseByIndexEvent,
MenuGoBackEvent, MenuGoHomeEvent, and MenuScrollEvent from the keypad reducer.
These events were previously handled by the Kivy GUI's MenuAppCentral.

This module subscribes to those events and dispatches the appropriate stack
actions so that the Redux state updates correctly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.logger import logger
from ubo_app.store.core.constants import PAGE_SIZE
from ubo_app.store.core.types import (
    ApplicationStackItem,
    CloseApplicationEvent,
    ExecuteMenuActionAction,
    ExecuteMenuActionEvent,
    MenuChooseByIconEvent,
    MenuChooseByIndexEvent,
    MenuChooseByLabelEvent,
    MenuGoBackEvent,
    MenuGoHomeEvent,
    MenuScrollDirection,
    MenuScrollEvent,
    MenuStackItem,
    NotificationStackItem,
    OpenApplicationEvent,
    StackPopAction,
    StackPopItemAction,
    StackPopToRootAction,
    StackPushApplicationAction,
    StackPushMenuAction,
    StackPushNotificationAction,
    StackSetPageIndexAction,
)
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    NotificationDisplayType,
    NotificationsClearEvent,
    NotificationsDisplayEvent,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_app.store.core.types import HomeViewData, MenuItemData, MenuViewData
    from ubo_app.utils.types import Subscriptions


def _handle_notification_choose_by_index(
    notification_id: str,
    index: int,
) -> bool:
    """Handle item selection on a notification view.

    Looks up the notification's computed view items and handles the action.
    Standard notification actions (dismiss, extra_info) are handled directly
    to avoid timing issues with the action registry. Custom actions fall back
    to ExecuteMenuActionAction.

    Returns True if the event was handled, False otherwise.
    """
    state = store._state  # noqa: SLF001
    if state is None:
        return False

    from ubo_app.store.core.view_computation import get_notification_view_data

    view_data = get_notification_view_data(state, notification_id)
    items = view_data.items
    if not items:
        return False

    # The notification widget pads items to PAGE_SIZE (3) with None at the
    # start so that items are bottom-aligned.  Index 0 = top button,
    # 1 = middle, 2 = bottom.  real_index = index - (PAGE_SIZE - len).
    real_items = [item for item in items if item is not None]
    pad = PAGE_SIZE - len(real_items)
    real_index = index - pad
    if real_index < 0 or real_index >= len(real_items):
        logger.debug(
            'Notification choose_by_index: index=%d has no item '
            '(real_index=%d, real_items=%d, pad=%d)',
            index,
            real_index,
            len(real_items),
            pad,
        )
        return False

    item = real_items[real_index]
    action_id = getattr(item, 'action_id', None)
    if not action_id:
        return False

    # Handle standard notification actions directly
    if action_id.startswith('notification:dismiss:'):
        _dismiss_notification(notification_id)
        return True

    if action_id.startswith('notification:extra_info:'):
        _show_extra_info(notification_id)
        return True

    # Custom notification actions go through the action registry
    store.dispatch(ExecuteMenuActionAction(action_id=action_id))
    return True


def _dismiss_notification(notification_id: str) -> None:
    """Dismiss a notification: pop from stack and clear from state."""
    from ubo_app.store.services.notifications import (
        Notification,
        NotificationsClearAction,
    )

    store.dispatch(StackPopAction())

    @store.with_state(lambda state: state.notifications.notifications)
    def clear_notification(
        notifications: Sequence[Notification],
    ) -> None:
        notif = next(
            (n for n in notifications if n.id == notification_id),
            None,
        )
        if notif:
            store.dispatch(NotificationsClearAction(notification=notif))

    clear_notification()


def _show_extra_info(notification_id: str) -> None:
    """Show a notification's extra information via speech synthesis."""
    from ubo_app.store.services.speech_synthesis import SpeechSynthesisReadTextAction

    state = store._state  # noqa: SLF001
    if state is None:
        return

    notification = next(
        (n for n in state.notifications.notifications if n.id == notification_id),
        None,
    )
    if notification and notification.extra_information:
        store.dispatch(
            SpeechSynthesisReadTextAction(information=notification.extra_information),
        )


def _execute_view_item_action(item: MenuItemData) -> bool:
    """Execute the action for a dynamic menu item.

    Returns True if the item was handled, False otherwise.
    """
    if not item.action_id:
        logger.info(
            '[MenuHandler] choose_by_index: current_view item label=%s '
            'has no action_id',
            item.label,
        )
        return False

    # notification:display:* action_ids open a notification by pushing it
    # onto the stack.
    if item.action_id.startswith('notification:display:'):
        notification_id = item.action_id[len('notification:display:'):]
        store.dispatch(StackPushNotificationAction(notification_id=notification_id))
        return True

    # menu:select:* action_ids are auto-generated for SubMenuItems.
    # These need StackPushMenuAction, not the action registry.
    if item.action_id.startswith('menu:select:'):
        menu_key = item.action_id[len('menu:select:'):]
        logger.info(
            '[MenuHandler] choose_by_index: pushing menu key=%s '
            'for label=%s',
            menu_key,
            item.label,
        )
        store.dispatch(StackPushMenuAction(menu_key=menu_key))
        return True

    logger.info(
        '[MenuHandler] choose_by_index: using current_view, '
        'executing action_id=%s for label=%s',
        item.action_id,
        item.label,
    )
    # Call execute_action directly (not via dispatch) so we can
    # handle return values -- handlers returning a Menu signal
    # that a sub-menu should be pushed onto the stack.
    from ubo_app.store.core.action_registry import execute_action

    result = execute_action(item.action_id)
    if result is not None and item.key:
        logger.info(
            '[MenuHandler] choose_by_index: action returned '
            'result, pushing key=%s',
            item.key,
        )
        store.dispatch(StackPushMenuAction(menu_key=item.key))
    return True


def _handle_home_view_index(
    current_view: HomeViewData,
    index: int,
) -> None:
    """Handle item selection on the home view.

    HomeViewData has no pagination, so ``index`` maps directly to items.
    """
    if not current_view.menu_items:
        logger.warning('[MenuHandler] choose_by_index: home view has no items')
        return

    item = (
        current_view.menu_items[index]
        if 0 <= index < len(current_view.menu_items)
        else None
    )
    if item is not None:
        _execute_view_item_action(item)
    else:
        logger.info(
            '[MenuHandler] choose_by_index: home item at index %d is None',
            index,
        )


def _handle_menu_view_index(
    current_view: MenuViewData,
    index: int,
) -> None:
    """Handle item selection on a paginated menu view."""
    if not current_view.items:
        logger.warning('[MenuHandler] choose_by_index: menu view has no items')
        return

    page_index = current_view.page_index

    # For headed menus, the heading/sub_heading occupy visual slots
    # on page 0, shifting which items map to which button indices.
    header_offset = 0
    if current_view.heading is not None:
        from ubo_app.store.core.constants import HEADED_MENU_HEADER_SLOTS

        header_offset = HEADED_MENU_HEADER_SLOTS

    actual_index = page_index * PAGE_SIZE + index - header_offset
    item = (
        current_view.items[actual_index]
        if 0 <= actual_index < len(current_view.items)
        else None
    )
    if item is None:
        logger.info(
            '[MenuHandler] choose_by_index: menu item at index %d is None '
            '(page=%d, actual=%d, total=%d)',
            index,
            page_index,
            actual_index,
            len(current_view.items),
        )
        return
    _execute_view_item_action(item)


def _handle_choose_by_index(event: MenuChooseByIndexEvent) -> None:
    """Handle menu item selection by index.

    Routes to a view-type-specific handler based on the current view.
    """
    from ubo_app.store.core.types import HomeViewData, MenuViewData

    state = store._state  # noqa: SLF001
    if state is None:
        logger.warning('[MenuHandler] choose_by_index: state is None')
        return

    top = state.main.stack[-1] if state.main.stack else None
    logger.info(
        '[MenuHandler] choose_by_index: index=%d, top=%s, stack_depth=%d',
        event.index,
        type(top).__name__ if top else 'None',
        len(state.main.stack),
    )

    # Handle notification items
    if isinstance(top, NotificationStackItem):
        _handle_notification_choose_by_index(top.notification_id, event.index)
        return

    # Route to view-type-specific handler
    current_view = state.main.current_view
    if isinstance(current_view, HomeViewData):
        _handle_home_view_index(current_view, event.index)
    elif isinstance(current_view, MenuViewData):
        _handle_menu_view_index(current_view, event.index)
    else:
        logger.debug(
            '[MenuHandler] choose_by_index: unhandled view type %s',
            type(current_view).__name__ if current_view else 'None',
        )


def _get_current_view_items(
    current_view: object,
) -> tuple[MenuItemData | None, ...]:
    """Extract menu items from any view type that has them."""
    from ubo_app.store.core.types import HomeViewData, MenuViewData

    if isinstance(current_view, HomeViewData) and current_view.menu_items:
        return current_view.menu_items
    if isinstance(current_view, MenuViewData) and current_view.items:
        return current_view.items
    return ()


def _handle_choose_by_icon(event: MenuChooseByIconEvent) -> None:
    """Handle menu item selection by icon."""
    state = store._state  # noqa: SLF001
    if state is None:
        return

    for item in _get_current_view_items(state.main.current_view):
        if item is not None and item.icon == event.icon:
            _execute_view_item_action(item)
            return

    logger.warning('No item with icon "%s"', event.icon)


def _handle_choose_by_label(event: MenuChooseByLabelEvent) -> None:
    """Handle menu item selection by label."""
    state = store._state  # noqa: SLF001
    if state is None:
        return

    for item in _get_current_view_items(state.main.current_view):
        if item is not None and item.label == event.label:
            _execute_view_item_action(item)
            return

    logger.warning('No item with label "%s"', event.label)


def _handle_go_back(_: MenuGoBackEvent) -> None:
    """Handle go back event."""
    store.dispatch(StackPopAction())


def _handle_go_home(_: MenuGoHomeEvent) -> None:
    """Handle go home event."""
    store.dispatch(StackPopToRootAction())


def _handle_scroll(event: MenuScrollEvent) -> None:
    """Handle menu scroll event."""
    from ubo_app.store.core.types import MenuViewData

    state = store._state  # noqa: SLF001
    if state is None:
        return

    stack = state.main.stack
    if not stack:
        return

    top = stack[-1]
    if not isinstance(top, MenuStackItem):
        return

    # Use pre-computed current_view for total_pages
    current_view = state.main.current_view
    if not isinstance(current_view, MenuViewData) or current_view.total_pages <= 0:
        return

    total_pages = current_view.total_pages
    page_index = top.page_index

    if event.direction == MenuScrollDirection.UP:
        new_page = (page_index - 1) % total_pages
    else:
        new_page = (page_index + 1) % total_pages

    if new_page != page_index:
        store.dispatch(StackSetPageIndexAction(page_index=new_page))


def _handle_execute_menu_action(event: ExecuteMenuActionEvent) -> None:
    """Handle menu action execution via the action registry.

    This is the side-effect layer for ExecuteMenuActionAction. The reducer
    emits ExecuteMenuActionEvent and this handler calls execute_action().
    If the handler returns a result and a menu_key was provided, it pushes
    the menu onto the stack.
    """
    from ubo_app.store.core.action_registry import execute_action

    result = execute_action(event.action_id)
    if result is not None and event.menu_key:
        store.dispatch(StackPushMenuAction(menu_key=event.menu_key))


def _handle_notification_display(event: NotificationsDisplayEvent) -> None:
    """Handle notification display by pushing it onto the stack."""
    notification = event.notification
    notification_id = getattr(notification, 'id', None)
    if not notification_id:
        logger.warning('NotificationsDisplayEvent with no notification ID')
        return
    store.dispatch(StackPushNotificationAction(notification_id=notification_id))

    # Schedule auto-dismiss for FLASH notifications
    if notification.display_type is NotificationDisplayType.FLASH:
        import asyncio

        from ubo_app.utils.async_ import create_task

        async def _auto_dismiss() -> None:
            await asyncio.sleep(notification.flash_time)
            _dismiss_notification(notification_id)

        create_task(_auto_dismiss())


def _handle_notification_clear(event: NotificationsClearEvent) -> None:
    """Handle notification clear by popping the matching stack item."""
    notification_id = getattr(event.notification, 'id', None)
    if not notification_id:
        return

    state = store._state  # noqa: SLF001
    if state is None:
        return

    # Find the NotificationStackItem with the matching notification_id
    for item in state.main.stack:
        if (
            isinstance(item, NotificationStackItem)
            and item.notification_id == notification_id
        ):
            logger.info(
                '[MenuHandler] notification_clear: popping notification %s',
                notification_id,
            )
            store.dispatch(StackPopItemAction(item_id=item.id))
            return


def _handle_open_application(event: OpenApplicationEvent) -> None:
    """Handle open application event by pushing an ApplicationStackItem."""
    store.dispatch(
        StackPushApplicationAction(
            application_id=event.application_id,
            initialization_args=event.initialization_args,
            initialization_kwargs=event.initialization_kwargs,
        ),
    )


def _handle_close_application(event: CloseApplicationEvent) -> None:
    """Handle close application event by popping the matching stack item."""
    state = store._state  # noqa: SLF001
    if state is None:
        return

    for item in state.main.stack:
        if (
            isinstance(item, ApplicationStackItem)
            and item.id == event.application_instance_id
        ):
            store.dispatch(StackPopItemAction(item_id=item.id))
            return


def setup_menu_event_handlers() -> Subscriptions:
    """Subscribe to menu events and wire them to stack actions."""
    return [
        store.subscribe_event(MenuChooseByIndexEvent, _handle_choose_by_index),
        store.subscribe_event(MenuChooseByIconEvent, _handle_choose_by_icon),
        store.subscribe_event(MenuChooseByLabelEvent, _handle_choose_by_label),
        store.subscribe_event(MenuGoBackEvent, _handle_go_back),
        store.subscribe_event(MenuGoHomeEvent, _handle_go_home),
        store.subscribe_event(MenuScrollEvent, _handle_scroll),
        store.subscribe_event(
            ExecuteMenuActionEvent,
            _handle_execute_menu_action,
        ),
        store.subscribe_event(
            NotificationsClearEvent,
            _handle_notification_clear,
        ),
        store.subscribe_event(
            NotificationsDisplayEvent,
            _handle_notification_display,
        ),
        store.subscribe_event(OpenApplicationEvent, _handle_open_application),
        store.subscribe_event(CloseApplicationEvent, _handle_close_application),
    ]
