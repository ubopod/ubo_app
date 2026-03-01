"""Helper for creating notification actions with registered callables."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from ubo_app.colors import SECONDARY_COLOR_LIGHT
from ubo_app.store.core.action_registry import register_action
from ubo_app.store.services.notifications import Color, NotificationActionItem

if TYPE_CHECKING:
    from collections.abc import Callable


def create_notification_action(  # noqa: PLR0913
    *,
    key: str = '',
    label: str = '',
    icon: str = '',
    action: Callable[[], object],
    dismiss_notification: bool = False,
    close_notification: bool = True,
    background_color: Color = SECONDARY_COLOR_LIGHT,
    color: str = '#ffffff',
) -> NotificationActionItem:
    """Create a NotificationActionItem with a registered callable action.

    This registers the callable in the action registry and returns a
    NotificationActionItem with the corresponding action_id. The action_id
    is accessible via the returned item's ``action_id`` attribute and can
    be used to unregister the action when the notification is cleared.
    """
    action_id = f'notification:custom:{uuid4().hex}'
    register_action(action_id, action)
    return NotificationActionItem(
        key=key,
        label=label,
        icon=icon,
        action_id=action_id,
        dismiss_notification=dismiss_notification,
        close_notification=close_notification,
        background_color=background_color,
        color=color,
    )
