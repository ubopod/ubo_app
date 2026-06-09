# ruff: noqa: D100, D103
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_handle import ReducerRegistrar, register

    from ubo_app.store.services.notifications import (
        Notification,
        NotificationActionItem,
    )

# Track registered action IDs to clean up on notification close
_registered_actions: dict[str, list[str]] = {}
_actions_lock = threading.Lock()


def _create_extra_info_handler(notification: Notification) -> None:
    """Register handler for showing notification extra info."""
    from ubo_app.logger import logger
    from ubo_app.store.core.action_registry import register_action
    from ubo_app.store.core.constants import NOTIFICATION_EXTRA_INFO_PREFIX
    from ubo_app.store.main import store
    from ubo_app.store.services.speech_synthesis import SpeechSynthesisReadTextAction

    if notification.extra_information is None:
        return

    action_id = f'{NOTIFICATION_EXTRA_INFO_PREFIX}{notification.id}'
    info = notification.extra_information

    def show_extra_info() -> None:
        store.dispatch(SpeechSynthesisReadTextAction(information=info))
        logger.info('Showing notification extra info')

    try:
        register_action(action_id, show_extra_info)
        with _actions_lock:
            _registered_actions.setdefault(notification.id, []).append(action_id)
    except ValueError:
        pass  # Already registered


def _create_dismiss_handler(notification: Notification) -> None:
    """Register handler for dismissing a notification."""
    from ubo_app.logger import logger
    from ubo_app.store.core.action_registry import register_action
    from ubo_app.store.core.constants import NOTIFICATION_DISMISS_PREFIX
    from ubo_app.store.main import store
    from ubo_app.store.services.notifications import NotificationsClearAction

    notification_id = notification.id
    action_id = f'{NOTIFICATION_DISMISS_PREFIX}{notification_id}'

    def dismiss() -> None:
        # NotificationsClearAction already pops this notification's overlay by
        # id (its reducer returns StackPopNotificationAction). A blind
        # StackPopAction() here would pop whatever is on *top* of the stack,
        # dismissing a second notification when this one isn't the top.
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
        logger.debug('Dismissed notification %s', notification_id)

    try:
        register_action(action_id, dismiss)
        with _actions_lock:
            _registered_actions.setdefault(notification_id, []).append(action_id)
    except ValueError:
        pass  # Already registered


def _dispatch_action_type(action: NotificationActionItem) -> None:
    """Dispatch store actions for dispatch/application notification items."""
    from ubo_app.store.main import store
    from ubo_app.store.services.notifications import (
        NotificationDispatchItem,
    )

    if isinstance(action, NotificationDispatchItem) and action.store_action:
        sa = action.store_action
        if isinstance(sa, list):
            store.dispatch(*sa)
        else:
            store.dispatch(sa)
    elif action.action_id:
        from ubo_app.logger import logger
        from ubo_app.store.core.action_registry import get_action

        handler = get_action(action.action_id)
        if handler:
            try:
                handler()
            except Exception:
                logger.exception('Error executing notification action')


def _handle_close_dismiss(
    action: NotificationActionItem,
    notification_id: str,
) -> None:
    """Handle close/dismiss behavior after action execution."""
    from ubo_app.store.core.types import StackPopNotificationAction
    from ubo_app.store.main import store
    from ubo_app.store.services.notifications import NotificationsClearAction

    # Close-only: pop *this* notification's overlay by id (not the stack top).
    # Dismiss: NotificationsClearAction below already pops it by id, so no
    # explicit pop is needed (and a blind pop would drop a second one).
    if action.close_notification and not action.dismiss_notification:
        store.dispatch(StackPopNotificationAction(notification_id=notification_id))

    if action.dismiss_notification:

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


def _create_action_handler(notification: Notification, action_index: int) -> None:
    """Register handler for a notification action."""
    from ubo_app.store.core.action_registry import register_action

    if action_index >= len(notification.actions):
        return

    action = notification.actions[action_index]
    notification_id = notification.id
    from ubo_app.store.core.constants import NOTIFICATION_ACTION_PREFIX

    action_id = f'{NOTIFICATION_ACTION_PREFIX}{notification_id}:{action_index}'

    def execute_action() -> None:
        _dispatch_action_type(action)
        _handle_close_dismiss(action, notification_id)

    try:
        register_action(action_id, execute_action)
        with _actions_lock:
            _registered_actions.setdefault(notification_id, []).append(action_id)
    except ValueError:
        pass  # Already registered


def _refresh_notification_action_handlers(notification: Notification) -> None:
    """(Re)register a notification's action handlers, replacing any prior set.

    A notification can be re-displayed under the same id with different actions
    (e.g. a multi-step setup flow that advances Fetch → Run → Download). Clearing
    the previous render's handlers first ensures the index-based
    ``notification:action:{id}:{index}`` handlers bind to the *current* actions —
    otherwise the stale handlers (which close over the old actions) stay bound,
    because ``_create_action_handler`` skips re-registration as "already
    registered", and the button keeps firing the old action.
    """
    from ubo_app.store.core.action_registry import unregister_action

    with _actions_lock:
        stale_action_ids = _registered_actions.pop(notification.id, [])
    for action_id in stale_action_ids:
        unregister_action(action_id)

    if notification.extra_information:
        _create_extra_info_handler(notification)

    for i in range(len(notification.actions)):
        _create_action_handler(notification, i)

    show_dismiss = getattr(notification, 'show_dismiss_action', True)
    if show_dismiss:
        _create_dismiss_handler(notification)


def _register_notification_action_handlers() -> None:
    """Register action handlers for notification actions."""
    from ubo_app.logger import logger
    from ubo_app.store.core.action_registry import unregister_action
    from ubo_app.store.main import store
    from ubo_app.store.services.notifications import (
        NotificationsClearEvent,
        NotificationsDisplayEvent,
    )

    def on_display(event: NotificationsDisplayEvent) -> None:
        notification = event.notification
        _refresh_notification_action_handlers(notification)

        with _actions_lock:
            if notification.id in _registered_actions:
                logger.debug(
                    'Registered %d handlers for notification %s',
                    len(_registered_actions[notification.id]),
                    notification.id,
                )

    def on_clear(event: NotificationsClearEvent) -> None:
        with _actions_lock:
            action_ids = _registered_actions.pop(event.notification.id, [])
        for action_id in action_ids:
            unregister_action(action_id)
        if action_ids:
            logger.debug(
                'Unregistered %d handlers for notification %s',
                len(action_ids),
                event.notification.id,
            )

    store.subscribe_event(NotificationsDisplayEvent, on_display)
    store.subscribe_event(NotificationsClearEvent, on_clear)


def setup(register_reducer: ReducerRegistrar) -> None:
    from reducer import reducer

    register_reducer(reducer)
    _register_notification_action_handlers()


register(
    service_id='notifications',
    label='Notifications',
    setup=setup,
)
