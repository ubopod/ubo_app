"""Menu event handlers for the headless core.

In the headless (dumb UI) architecture, the core emits MenuChooseByIndexEvent
from the keypad reducer. This module subscribes to those events and dispatches
the appropriate stack actions so that the Redux state updates correctly.

Navigation events (go back, go home, scroll, open/close application) are now
handled directly by the reducer — no event round-trip needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.logger import logger
from ubo_app.store.core.constants import (
    MENU_SELECT_PREFIX,
    NOTIFICATION_ACTION_PREFIX,
    NOTIFICATION_DISMISS_PREFIX,
    NOTIFICATION_DISPLAY_PREFIX,
    NOTIFICATION_EXTRA_INFO_PREFIX,
    PAGE_SIZE,
    compute_total_pages,
)
from ubo_app.store.core.types import (
    ExecuteMenuActionAction,
    ExecuteMenuActionEvent,
    MenuChooseByIconEvent,
    MenuChooseByIndexEvent,
    MenuChooseByLabelEvent,
    NotificationStackItem,
    StackPopAction,
    StackPopNotificationAction,
    StackPushMenuAction,
    StackPushNotificationAction,
)
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    NotificationDisplayType,
    NotificationsClearEvent,
    NotificationsDisplayEvent,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_app.store.core.types import (
        ApplicationStackItem,
        HomeViewData,
        MainAction,
        MenuItemData,
        MenuViewData,
        PromptStackItem,
    )
    from ubo_app.store.main import RootState
    from ubo_app.utils.types import Subscriptions


def _dispatch_original_notification_action(
    state: RootState,
    notification_id: str,
    action_id: str,
) -> bool:
    """Look up the original notification action and dispatch it.

    Handles NotificationDispatchItem (store_action) by dispatching
    the appropriate actions. Returns True if handled.
    """
    if not hasattr(state, 'notifications') or not action_id.startswith(
        NOTIFICATION_ACTION_PREFIX,
    ):
        return False

    notification = next(
        (n for n in state.notifications.notifications if n.id == notification_id),
        None,
    )
    if not notification:
        return False

    # Extract the action index from the action_id
    suffix = action_id[len(NOTIFICATION_ACTION_PREFIX) + len(notification_id) + 1 :]
    action_index = int(suffix) if suffix.isdigit() else -1
    if action_index < 0 or action_index >= len(notification.actions):
        return False

    from ubo_app.store.services.notifications import (
        NotificationDispatchItem,
    )

    original_action = notification.actions[action_index]

    # Handle dismiss/close flags
    if original_action.dismiss_notification:
        _dismiss_notification(notification_id)
    elif original_action.close_notification:
        store.dispatch(StackPopAction())

    # Handle NotificationDispatchItem (has store_action)
    if (
        isinstance(original_action, NotificationDispatchItem)
        and original_action.store_action is not None
    ):
        actions = (
            original_action.store_action
            if isinstance(original_action.store_action, list)
            else [original_action.store_action]
        )
        store.dispatch(*actions)
        return True

    # If the original action has a registered action_id, use it
    if original_action.action_id:
        store.dispatch(
            ExecuteMenuActionAction(action_id=original_action.action_id),
        )
        return True

    return False


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

    @store.with_state(lambda state: state)
    def _get_state(state: RootState) -> RootState:
        return state

    state = _get_state()
    if state is None:
        return False

    from ubo_app.store.core.view_computation import (
        get_notification_view_data,
        visible_stack,
    )

    # Get page_index from the *visible* top notification (BACKGROUND overlays
    # are filtered out, matching the view computation).
    stack = visible_stack(state)
    top = stack[-1] if stack else None
    notif_page_index = (
        top.page_index
        if isinstance(top, NotificationStackItem)
        else 0
    )

    view_data = get_notification_view_data(
        state, notification_id, page_index=notif_page_index,
    )
    all_items = [item for item in view_data.items if item is not None]
    if not all_items:
        return False

    # Slice to the current page's items (same logic the GUI uses).
    total_pages = compute_total_pages(len(all_items))
    page_start = notif_page_index * PAGE_SIZE
    page_items = all_items[page_start : page_start + PAGE_SIZE]
    if not page_items:
        return False

    # Single-page notifications are bottom-aligned (pad at top).
    # Multi-page notifications are top-aligned (like regular menus).
    if total_pages <= 1:
        pad = PAGE_SIZE - len(page_items)
        real_index = index - pad
    else:
        pad = 0
        real_index = index
    if real_index < 0 or real_index >= len(page_items):
        logger.debug(
            'Notification choose_by_index: index=%d has no item '
            '(real_index=%d, page_items=%d, pad=%d, page=%d)',
            index,
            real_index,
            len(page_items),
            pad,
            notif_page_index,
        )
        return False

    item = page_items[real_index]
    action_id = getattr(item, 'action_id', None)
    if not action_id:
        return False

    return _dispatch_notification_item_action(notification_id, action_id)


def _dispatch_notification_item_action(
    notification_id: str,
    action_id: str,
) -> bool:
    """Dispatch the action for a notification item by action_id."""
    # Handle standard notification actions directly
    if action_id.startswith(NOTIFICATION_DISMISS_PREFIX):
        _dismiss_notification(notification_id)
        return True

    if action_id.startswith(NOTIFICATION_EXTRA_INFO_PREFIX):
        _show_extra_info(notification_id)
        return True

    # Dispatch via the action registry. The 010-notifications service registers
    # handlers for notification:action:{id}:{index} that call the correct
    # handler (_dispatch_action_type → handle close/dismiss).
    from ubo_app.store.core.action_registry import execute_action

    execute_action(action_id)
    return True


def _dismiss_notification(notification_id: str) -> None:
    """Dismiss a notification: pop from stack and clear from state."""
    from ubo_app.store.services.notifications import (
        Notification,
        NotificationsClearAction,
    )

    store.dispatch(StackPopNotificationAction(notification_id=notification_id))

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
    from ubo_app.store.services.notifications import Notification
    from ubo_app.store.services.speech_synthesis import SpeechSynthesisReadTextAction

    @store.with_state(lambda state: state.notifications.notifications)
    def _dispatch_speech(
        notifications: Sequence[Notification],
    ) -> None:
        notification = next(
            (n for n in notifications if n.id == notification_id),
            None,
        )
        if notification and notification.extra_information:
            store.dispatch(
                SpeechSynthesisReadTextAction(
                    information=notification.extra_information,
                ),
            )

    _dispatch_speech()


def _execute_view_item_action(item: MenuItemData) -> bool:
    """Execute the action for a dynamic menu item.

    Returns True if the item was handled, False otherwise.
    """
    action = _resolve_view_item_action(item)
    if action is None:
        return False
    store.dispatch(action)
    return True


def _resolve_view_item_action(item: MenuItemData) -> MainAction | None:
    """Map a selected view item to the reducer action that handles it."""
    if not item.action_id:
        logger.info(
            '[MenuHandler] choose_by_index: current_view item label=%s '
            'has no action_id',
            item.label,
        )
        return None

    # notification:display:* action_ids open a notification by pushing it
    # onto the stack.
    if item.action_id.startswith(NOTIFICATION_DISPLAY_PREFIX):
        notification_id = item.action_id[len(NOTIFICATION_DISPLAY_PREFIX):]
        return StackPushNotificationAction(notification_id=notification_id)

    # menu:select:* action_ids are auto-generated for SubMenuItems.
    # These need StackPushMenuAction, not the action registry.
    if item.action_id.startswith(MENU_SELECT_PREFIX):
        menu_key = item.action_id[len(MENU_SELECT_PREFIX):]
        logger.info(
            '[MenuHandler] choose_by_index: pushing menu key=%s '
            'for label=%s',
            menu_key,
            item.label,
        )
        return StackPushMenuAction(menu_key=menu_key)

    logger.info(
        '[MenuHandler] choose_by_index: using current_view, '
        'executing action_id=%s for label=%s',
        item.action_id,
        item.label,
    )
    return ExecuteMenuActionAction(action_id=item.action_id, menu_key=item.key)


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
    from ubo_app.store.core.types import (
        ApplicationStackItem,
        HomeViewData,
        MenuViewData,
        PromptStackItem,
    )

    @store.with_state(lambda state: state)
    def _get_state(state: RootState) -> RootState:
        return state

    state = _get_state()
    if state is None:
        logger.warning('[MenuHandler] choose_by_index: state is None')
        return

    # Resolve the *visible* top — BACKGROUND/mid-dismissal notification
    # overlays sit on the raw stack top but are filtered out of the view, so a
    # button press must act on what the user actually sees underneath them.
    from ubo_app.store.core.view_computation import visible_stack

    stack = visible_stack(state)
    top = stack[-1] if stack else None
    logger.debug(
        '[MenuHandler] choose_by_index: index=%d, top=%s, stack_depth=%d',
        event.index,
        type(top).__name__ if top else 'None',
        len(stack),
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
    elif isinstance(top, ApplicationStackItem):
        _handle_application_view_index(top, event.index)
    elif isinstance(top, PromptStackItem):
        _handle_prompt_view_index(top, event.index)
    else:
        logger.debug(
            '[MenuHandler] choose_by_index: unhandled view type %s',
            type(current_view).__name__ if current_view else 'None',
        )


def _handle_application_view_index(
    top: ApplicationStackItem,
    index: int,
) -> None:
    """Handle button press on an application view.

    Dispatches ``ExecuteMenuActionAction`` with action_id
    ``app-button:{application_id}:{index}`` so services can register
    handlers for their application pages.
    """
    action_id = f'app-button:{top.application_id}:{index}'
    logger.debug(
        '[MenuHandler] choose_by_index: application button action_id=%s',
        action_id,
    )
    store.dispatch(ExecuteMenuActionAction(action_id=action_id))


def _handle_prompt_view_index(
    top: PromptStackItem,
    index: int,
) -> None:
    """Handle button press on a prompt view.

    Maps the button index to the prompt's items and executes the action_id.
    Prompt items are bottom-aligned (like notification items), so index 1
    maps to the first item, index 2 to the second, etc.
    """
    from ubo_app.store.core.constants import PAGE_SIZE

    items = top.items
    if not items:
        return

    # Items are bottom-aligned: index maps from PAGE_SIZE - len(items)
    item_index = index - (PAGE_SIZE - len(items))
    if item_index < 0 or item_index >= len(items):
        logger.debug(
            '[MenuHandler] choose_by_index: prompt index %d out of range',
            index,
        )
        return

    item = items[item_index]
    if item and item.action_id:
        logger.info(
            '[MenuHandler] choose_by_index: prompt action_id=%s for label=%s',
            item.action_id,
            item.label,
        )
        store.dispatch(ExecuteMenuActionAction(action_id=item.action_id))


def _get_current_view_items(
    current_view: object,
) -> tuple[MenuItemData | None, ...]:
    """Extract menu items from any view type that has them."""
    from ubo_app.store.core.types import (
        HomeViewData,
        MenuViewData,
        NotificationViewData,
    )

    if isinstance(current_view, HomeViewData) and current_view.menu_items:
        return current_view.menu_items
    if isinstance(current_view, MenuViewData | NotificationViewData) \
                and current_view.items:
        return current_view.items
    return ()


def _handle_choose_by_field(
    field: str,
    value: str,
) -> None:
    """Handle menu item selection by a specific field (icon or label)."""

    @store.with_state(lambda state: state.main.current_view)
    def _find_and_execute(current_view: object) -> None:
        for item in _get_current_view_items(current_view):
            if item is not None and getattr(item, field) == value:
                _execute_view_item_action(item)
                return

        logger.warning('No item with %s "%s"', field, value)

    _find_and_execute()


def _handle_choose_by_icon(event: MenuChooseByIconEvent) -> None:
    """Handle menu item selection by icon."""
    _handle_choose_by_field('icon', event.icon)


def _handle_choose_by_label(event: MenuChooseByLabelEvent) -> None:
    """Handle menu item selection by label."""
    _handle_choose_by_field('label', event.label)


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
    """Schedule the auto-dismiss timer for FLASH notifications.

    Pushing/popping the notification's stack item is *not* done here.
    Event handlers run in concurrent worker threads, so deciding stack
    membership from this handler raced — out-of-order push/pop dispatches
    made the first STICKY and the terminal FLASH vanish. Stack
    reconciliation now happens in the notifications reducer
    (``_stack_action_for``), on the ordered action queue. This handler
    only owns the FLASH auto-dismiss timer, which is purely time-based
    and has no ordering sensitivity.
    """
    notification = event.notification
    notification_id = getattr(notification, 'id', None)
    if not notification_id:
        logger.warning('NotificationsDisplayEvent with no notification ID')
        return

    if notification.display_type is not NotificationDisplayType.FLASH:
        return

    import asyncio

    from ubo_app.store.services.notifications import Notification
    from ubo_app.utils.async_ import create_task

    async def _auto_dismiss() -> None:
        await asyncio.sleep(notification.flash_time)

        # Re-check the *current* notification before dismissing. A
        # notification can be updated from FLASH back to STICKY/BACKGROUND
        # and multiple FLASH updates each schedule their own timer.
        # Without this guard a stale timer would close an active
        # notification.
        @store.with_state(lambda state: state.notifications.notifications)
        def _dismiss_if_still_flash(
            notifications: Sequence[Notification],
        ) -> None:
            current = next(
                (n for n in notifications if n.id == notification_id),
                None,
            )
            if (
                current is not None
                and current.display_type is NotificationDisplayType.FLASH
            ):
                _dismiss_notification(notification_id)

        _dismiss_if_still_flash()

    create_task(_auto_dismiss())


def _handle_notification_clear_callback(event: NotificationsClearEvent) -> None:
    """Fire a cleared notification's ``on_close_id`` callback.

    Producers (e.g. ``InputDemand``-driven flows in the camera,
    file-system and web-ui services) register a callback via
    ``register_auto_callback`` and stash its id on the notification so
    the cancel signal fires when the notification leaves state. The old
    GUI's client-side ``MenuNotificationHandler.close()`` did this hop;
    in the headless / view-renderer architecture the trigger has to be
    server-side, otherwise the callbacks become silently dead and any
    downstream cleanup (e.g. draining the camera's input queue) stalls.
    """
    on_close_id = getattr(event.notification, 'on_close_id', None)
    if not on_close_id:
        return
    from ubo_app.store.core.callback_registry import (
        execute_callback,
        unregister_callback,
    )

    execute_callback(on_close_id)
    unregister_callback(on_close_id)


def setup_menu_event_handlers() -> Subscriptions:
    """Subscribe to menu events and wire them to stack actions."""
    return [
        store.subscribe_event(MenuChooseByIndexEvent, _handle_choose_by_index),
        store.subscribe_event(MenuChooseByIconEvent, _handle_choose_by_icon),
        store.subscribe_event(MenuChooseByLabelEvent, _handle_choose_by_label),
        store.subscribe_event(
            ExecuteMenuActionEvent,
            _handle_execute_menu_action,
        ),
        # Notification stack push/pop is reconciled by the notifications
        # reducer (ordered action queue); this handler only schedules the
        # FLASH auto-dismiss timer.
        store.subscribe_event(
            NotificationsDisplayEvent,
            _handle_notification_display,
        ),
        store.subscribe_event(
            NotificationsClearEvent,
            _handle_notification_clear_callback,
        ),
    ]
