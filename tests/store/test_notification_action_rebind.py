"""Tests for notification action-handler rebinding on re-display.

A notification re-displayed under the same id with different actions (e.g. a
multi-step setup flow) must rebind its index-based ``notification:action:{id}:{i}``
handlers to the *current* actions — otherwise a stale handler keeps firing the
old action.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

_UBO_HANDLE_PATH = (
    Path(__file__).parents[2]
    / 'ubo_app'
    / 'services'
    / '010-notifications'
    / 'ubo_handle.py'
)


def _noop_register(**_kwargs: object) -> None:
    """Stand in for the service-loader-injected ``register`` global."""


def _load_notifications_ubo_handle() -> ModuleType:
    """Load the 010-notifications ubo_handle module under a unique name.

    A unique module name avoids colliding with the ``ubo_handle`` modules of
    other services in the same test session. The module's top-level imports are
    light (no store), but it ends with a ``register(...)`` service-registration
    call whose ``register`` global is normally injected by the service loader;
    we stub it so the module loads without side effects (``setup`` is only
    passed as a callback, never invoked here).
    """
    spec = importlib.util.spec_from_file_location(
        'notifications_ubo_handle_under_test',
        _UBO_HANDLE_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    module.register = _noop_register  # type: ignore[attr-defined]
    spec.loader.exec_module(module)
    return module


def test_redisplay_rebinds_action_handler() -> None:
    """Re-displaying a same-id notification rebinds its index-0 handler."""
    # Resolve registry/constant/types at runtime (not module import time): the
    # exec-loaded ubo_handle module registers via deferred imports, so the full
    # Docker suite — where integration tests churn ``sys.modules`` — can leave a
    # top-level import bound to a stale module generation (a different
    # ``_registry`` singleton than the one the handler registers into).
    from ubo_app.store.core.action_registry import clear_all_actions, get_action
    from ubo_app.store.core.constants import NOTIFICATION_ACTION_PREFIX
    from ubo_app.store.services.notifications import (
        Notification,
        NotificationActionItem,
    )

    clear_all_actions()
    module = _load_notifications_ubo_handle()

    notification_id = 'test:rebind'
    action_id = f'{NOTIFICATION_ACTION_PREFIX}{notification_id}:0'

    first = Notification(
        id=notification_id,
        title='Setup',
        content='Step one',
        actions=[NotificationActionItem(key='a', label='First')],
        show_dismiss_action=False,
    )
    module._refresh_notification_action_handlers(first)  # noqa: SLF001
    first_handler = get_action(action_id)
    assert first_handler is not None

    second = Notification(
        id=notification_id,
        title='Setup',
        content='Step two',
        actions=[NotificationActionItem(key='b', label='Second')],
        show_dismiss_action=False,
    )
    module._refresh_notification_action_handlers(second)  # noqa: SLF001
    second_handler = get_action(action_id)
    assert second_handler is not None

    # The handler must be rebound to the second render; a stale first-render
    # handler (the bug) would leave ``first_handler`` in place.
    assert second_handler is not first_handler
