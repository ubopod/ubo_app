# ruff: noqa: D100, D103
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ubo_handle import ReducerRegistrar, register

# Track registered action IDs to clean up on notification close
_registered_actions: dict[str, list[str]] = {}


def _create_extra_info_handler(notification_id: str) -> None:
    """Register handler for showing notification extra info."""
    from ubo_app.logger import logger
    from ubo_app.store.core.action_registry import register_action
    from ubo_app.store.main import store
    from ubo_app.store.services.speech_synthesis import SpeechSynthesisReadTextAction

    # Get the notification from store
    state = store._state  # noqa: SLF001
    if state is None:
        return

    notification = next(
        (n for n in state.notifications.notifications if n.id == notification_id),
        None,
    )
    if notification is None or notification.extra_information is None:
        return

    action_id = f'notification:extra_info:{notification_id}'
    info = notification.extra_information

    def show_extra_info() -> None:
        store.dispatch(SpeechSynthesisReadTextAction(information=info))
        logger.info('Showing notification extra info')

    try:
        register_action(action_id, show_extra_info)
        _registered_actions.setdefault(notification_id, []).append(action_id)
    except ValueError:
        pass  # Already registered


def _create_action_handler(notification_id: str, action_index: int) -> None:  # noqa: C901
    """Register handler for a notification action."""
    from ubo_app.logger import logger
    from ubo_app.store.core.action_registry import register_action
    from ubo_app.store.core.types import StackPopAction
    from ubo_app.store.main import store
    from ubo_app.store.services.notifications import NotificationsClearAction

    state = store._state  # noqa: SLF001
    if state is None:
        return

    notification = next(
        (n for n in state.notifications.notifications if n.id == notification_id),
        None,
    )
    if notification is None or action_index >= len(notification.actions):
        return

    action = notification.actions[action_index]
    action_id = f'notification:action:{notification_id}:{action_index}'

    def execute_action() -> None:
        # Execute the action's callback
        action_func = getattr(action, 'action', None)
        if callable(action_func):
            try:
                action_func()
            except Exception:
                logger.exception('Error executing notification action')

        # Check if we should close/dismiss
        close = getattr(action, 'close_notification', True)
        dismiss = getattr(action, 'dismiss_notification', False)

        if close or dismiss:
            store.dispatch(StackPopAction())

        if dismiss:
            # Re-fetch notification for clearing
            current_state = store._state  # noqa: SLF001
            if current_state:
                notif = next(
                    (n for n in current_state.notifications.notifications
                     if n.id == notification_id),
                    None,
                )
                if notif:
                    store.dispatch(NotificationsClearAction(notification=notif))

    try:
        register_action(action_id, execute_action)
        _registered_actions.setdefault(notification_id, []).append(action_id)
    except ValueError:
        pass  # Already registered


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
        if notification.extra_information:
            _create_extra_info_handler(notification.id)

        for i in range(len(notification.actions)):
            _create_action_handler(notification.id, i)

        if notification.id in _registered_actions:
            logger.debug(
                'Registered %d handlers for notification %s',
                len(_registered_actions[notification.id]),
                notification.id,
            )

    def on_clear(event: NotificationsClearEvent) -> None:
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
