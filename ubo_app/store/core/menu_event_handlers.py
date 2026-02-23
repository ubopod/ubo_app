"""Menu event handlers for the headless core.

In the headless (dumb UI) architecture, the core emits MenuChooseByIndexEvent,
MenuGoBackEvent, MenuGoHomeEvent, and MenuScrollEvent from the keypad reducer.
These events were previously handled by the Kivy GUI's MenuAppCentral.

This module subscribes to those events and dispatches the appropriate stack
actions so that the Redux state updates correctly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_gui.menu.types import (  # pyright: ignore[reportMissingImports]
    ActionItem,
    SubMenuItem,
    menu_items,
)

from ubo_app.logger import logger
from ubo_app.store.core.constants import PAGE_SIZE
from ubo_app.store.core.menu_adapter import get_current_menu_from_stack
from ubo_app.store.core.types import (
    ExecuteMenuActionAction,
    MenuChooseByIconEvent,
    MenuChooseByIndexEvent,
    MenuChooseByLabelEvent,
    MenuGoBackEvent,
    MenuGoHomeEvent,
    MenuScrollDirection,
    MenuScrollEvent,
    MenuStackItem,
    NotificationStackItem,
    StackPopAction,
    StackPopItemAction,
    StackPopToRootAction,
    StackPushMenuAction,
    StackPushNotificationAction,
    StackSetPageIndexAction,
)
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    NotificationsClearEvent,
    NotificationsDisplayEvent,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_gui.menu.types import Item

    from ubo_app.utils.types import Subscriptions


def _select_item(item: Item) -> None:
    """Execute the selection logic for a menu item."""
    if isinstance(item, SubMenuItem):
        key = getattr(item, 'key', None)
        if key:
            logger.info('[MenuHandler] _select_item: pushing SubMenuItem key=%s', key)
            store.dispatch(StackPushMenuAction(menu_key=key))
        else:
            logger.warning('SubMenuItem has no key, cannot navigate')
    elif isinstance(item, ActionItem) and item.action:
        try:
            logger.info('[MenuHandler] _select_item: executing ActionItem action')
            result = item.action()
            if result is not None:
                key = getattr(item, 'key', None)
                logger.info(
                    '[MenuHandler] _select_item: ActionItem returned result, '
                    'pushing key=%s',
                    key,
                )
                if key:
                    store.dispatch(StackPushMenuAction(menu_key=key))
        except Exception:
            logger.exception('Error executing menu item action')
    else:
        logger.info(
            '[MenuHandler] _select_item: unhandled item type=%s',
            type(item).__name__,
        )


def _get_current_items() -> list[Item] | None:
    """Get current menu items from the store state.

    WARNING: This traverses the static menu tree, which may call autorun-wrapped
    callables (sub_menu(), items()) that deadlock outside service context.
    Callers must wrap this in try/except.
    """
    state = store._state  # noqa: SLF001
    if state is None:
        logger.info('[MenuHandler] _get_current_items: state is None')
        return None
    stack = state.main.stack
    root_menu = state.main.menu
    if not stack or root_menu is None:
        logger.info('[MenuHandler] _get_current_items: no stack or root_menu')
        return None
    menu_path = [
        item.menu_key
        for item in stack
        if isinstance(item, MenuStackItem)
    ]
    logger.info('[MenuHandler] _get_current_items: menu_path=%s', menu_path)

    # Check if menu.items is a callable (autorun wrapper) before traversal.
    # If so, calling it outside service context will deadlock for 30s.
    current_menu = get_current_menu_from_stack(root_menu, stack)
    if current_menu is None:
        logger.info('[MenuHandler] _get_current_items: menu not found in tree')
        return None
    if callable(current_menu.items):
        logger.warning(
            '[MenuHandler] _get_current_items: menu.items is callable '
            '(autorun wrapper), skipping to avoid deadlock',
        )
        return None
    items = list(menu_items(current_menu))
    logger.info(
        '[MenuHandler] _get_current_items: found %d items',
        len(items),
    )
    return items


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


def _handle_choose_by_index(event: MenuChooseByIndexEvent) -> None:
    """Handle menu item selection by index."""
    from ubo_app.store.core.types import MenuViewData

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

    # Try using the pre-computed current_view first. This avoids calling
    # autorun-wrapped callables (sub_menu(), items()) during menu tree
    # traversal, which can deadlock outside service context.
    current_view = state.main.current_view
    logger.info(
        '[MenuHandler] choose_by_index: current_view type=%s, has_items=%s',
        type(current_view).__name__ if current_view else 'None',
        bool(getattr(current_view, 'items', None)),
    )
    if isinstance(current_view, MenuViewData) and current_view.items:
        page_index = top.page_index if isinstance(top, MenuStackItem) else 0
        actual_index = page_index * PAGE_SIZE + event.index
        item = current_view.items[actual_index] if actual_index < len(
            current_view.items,
        ) else None
        if item is None:
            logger.info(
                '[MenuHandler] choose_by_index: current_view item at index %d '
                'is None (page=%d, actual=%d, total=%d)',
                event.index,
                page_index,
                actual_index,
                len(current_view.items),
            )
            return
        if item.action_id:
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
                return
            logger.info(
                '[MenuHandler] choose_by_index: using current_view, '
                'dispatching action_id=%s for label=%s',
                item.action_id,
                item.label,
            )
            store.dispatch(ExecuteMenuActionAction(action_id=item.action_id))
            return
        # Item exists but has no action_id — fall through to static menu
        # which can resolve SubMenuItem/ActionItem directly.
        logger.info(
            '[MenuHandler] choose_by_index: current_view item label=%s '
            'has no action_id, falling through to static menu',
            item.label,
        )

    # Fall back to static menu tree traversal for menus that don't use
    # the dynamic/view system (legacy path).
    # NOTE: This can deadlock/crash when menu items or sub_menu are autorun
    # wrappers called outside service context. Catch all exceptions to prevent
    # the handler from crashing the event loop.
    try:
        items = _get_current_items()
    except Exception:
        logger.exception(
            '[MenuHandler] choose_by_index: _get_current_items() failed '
            '(likely autorun outside service context)',
        )
        return
    if items is None:
        logger.warning('[MenuHandler] choose_by_index: no current items')
        return

    # Account for page_index
    page_index = top.page_index if isinstance(top, MenuStackItem) else 0
    actual_index = page_index * PAGE_SIZE + event.index

    logger.info(
        '[MenuHandler] choose_by_index: page=%d, actual_index=%d, total_items=%d',
        page_index,
        actual_index,
        len(items),
    )

    if actual_index >= len(items):
        logger.info(
            '[MenuHandler] choose_by_index: index %d out of range (items=%d)',
            actual_index,
            len(items),
        )
        return

    item = items[actual_index]
    if item is not None:
        label = getattr(item, 'label', None)
        label_val = label() if callable(label) else label
        logger.info(
            '[MenuHandler] choose_by_index: selecting item label=%s, type=%s',
            label_val,
            type(item).__name__,
        )
        _select_item(item)


def _handle_choose_by_icon(event: MenuChooseByIconEvent) -> None:
    """Handle menu item selection by icon."""
    items = _get_current_items()
    if items is None:
        return

    for item in items:
        if item is None:
            continue
        icon = getattr(item, 'icon', None)
        icon_val = icon() if callable(icon) else icon
        if icon_val == event.icon:
            _select_item(item)
            return

    logger.warning('No item with icon "%s"', event.icon)


def _handle_choose_by_label(event: MenuChooseByLabelEvent) -> None:
    """Handle menu item selection by label."""
    items = _get_current_items()
    if items is None:
        return

    for item in items:
        if item is None:
            continue
        label = getattr(item, 'label', None)
        label_val = label() if callable(label) else label
        if label_val == event.label:
            _select_item(item)
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
    state = store._state  # noqa: SLF001
    if state is None:
        return

    stack = state.main.stack
    if not stack:
        return

    top = stack[-1]
    if not isinstance(top, MenuStackItem):
        return

    # Use pre-computed current_view (same pattern as _handle_choose_by_index)
    from ubo_app.store.core.types import MenuViewData

    current_view = state.main.current_view
    if isinstance(current_view, MenuViewData) and current_view.total_pages > 0:
        total_pages = current_view.total_pages
    else:
        # Fallback to item counting
        items = _get_current_items()
        if items is None:
            return
        total_pages = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)

    page_index = top.page_index

    if event.direction == MenuScrollDirection.UP:
        new_page = (page_index - 1) % total_pages
    else:
        new_page = (page_index + 1) % total_pages

    if new_page != page_index:
        store.dispatch(StackSetPageIndexAction(page_index=new_page))


def _handle_notification_display(event: NotificationsDisplayEvent) -> None:
    """Handle notification display by pushing it onto the stack."""
    notification_id = getattr(event.notification, 'id', None)
    if not notification_id:
        logger.warning('NotificationsDisplayEvent with no notification ID')
        return
    store.dispatch(StackPushNotificationAction(notification_id=notification_id))


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
            NotificationsClearEvent,
            _handle_notification_clear,
        ),
        store.subscribe_event(
            NotificationsDisplayEvent,
            _handle_notification_display,
        ),
    ]
