"""Tests for the notifications reducer reconciling the navigation stack.

Stack push/pop for notifications is returned from the reducer (on the
ordered action queue) rather than from a ``NotificationsDisplayEvent``
handler — event handlers run in concurrent worker threads, so deciding
stack membership there raced and made the first STICKY / terminal FLASH
notification of a download flow vanish.

Class-identity discipline: integration tests earlier in the suite wipe
``sys.modules`` (see ``tests/fixtures/app.py``), so any module-level
``from ubo_app.store.services.notifications import …`` performed at
collection time becomes stale by the time these tests run. The loader
explicitly ``importlib.reload``s the store-side modules and then
``exec_module``s the reducer, so when the reducer's own imports resolve
they see the same freshly-loaded module objects. Tests pull every
action / state / type from the returned namespace — never from
top-level imports — to keep the class objects identical on both sides
of ``isinstance`` / ``match``/``case`` checks.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import pytest
    from redux import BaseAction

    # Static-only: never executed at runtime, so doesn't trigger a fresh
    # ``ubo_app.store.services.notifications`` import that would break
    # the class-identity discipline. Production code paths use
    # ``ns.NotificationsState`` (the freshly-reloaded class) — these
    # imports give pyright/ruff the structural type to validate against.
    from ubo_app.store.services.notifications import NotificationsState


SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/010-notifications'


def _load_notifications(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Load the notifications reducer + a namespace of its public classes.

    Reloading ``ubo_app.store.core.types`` and
    ``ubo_app.store.services.notifications`` before the reducer's own
    ``exec_module`` is what makes this safe under the
    ``tests/fixtures/app.py`` sys-modules cleanup: every class object
    exposed on the returned namespace is the *same* one the reducer
    closes over inside its ``match action: case …`` arms.
    """
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())

    from ubo_app.store.core import types as core_types
    from ubo_app.store.core import view_computation
    from ubo_app.store.services import notifications as notifications_module

    core_types = importlib.reload(core_types)
    notifications_module = importlib.reload(notifications_module)
    view_computation = importlib.reload(view_computation)

    spec = importlib.util.spec_from_file_location(
        'notifications_service_reducer',
        SERVICE_PATH / 'reducer.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    return SimpleNamespace(
        reducer=module.reducer,
        # store/services/notifications
        Notification=notifications_module.Notification,
        NotificationsState=notifications_module.NotificationsState,
        NotificationDisplayType=notifications_module.NotificationDisplayType,
        NotificationsAddAction=notifications_module.NotificationsAddAction,
        NotificationsClearAction=notifications_module.NotificationsClearAction,
        NotificationsClearByIdAction=(
            notifications_module.NotificationsClearByIdAction
        ),
        # store/core/types
        MenuStackItem=core_types.MenuStackItem,
        NotificationStackItem=core_types.NotificationStackItem,
        StackPopNotificationAction=core_types.StackPopNotificationAction,
        StackPushNotificationAction=core_types.StackPushNotificationAction,
        # store/core/view_computation
        is_background_notification=view_computation._is_background_notification,  # noqa: SLF001
    )


def _init_state(ns: SimpleNamespace) -> NotificationsState:
    """Initialise the reducer with the InitAction from its own globals."""
    init_action_type = cast(
        'type[BaseAction]',
        ns.reducer.__globals__['InitAction'],
    )
    return cast('NotificationsState', ns.reducer(None, init_action_type()))


def _actions_of(result: object) -> list[object]:
    return list(getattr(result, 'actions', None) or [])


def test_sticky_notification_pushes_onto_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A STICKY notification add returns a push action for its id."""
    ns = _load_notifications(monkeypatch)
    state = _init_state(ns)

    result = ns.reducer(
        state,
        ns.NotificationsAddAction(
            notification=ns.Notification(
                id='dl',
                title='Downloading',
                content='',
                display_type=ns.NotificationDisplayType.STICKY,
            ),
        ),
    )
    actions = _actions_of(result)
    assert any(
        isinstance(a, ns.StackPushNotificationAction)
        and getattr(a, 'notification_id', None) == 'dl'
        for a in actions
    )


def test_background_notification_still_pushes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A BACKGROUND notification add still returns a *push* action.

    The notification's ``NotificationStackItem`` stays on the stack for
    its whole lifecycle — no push/pop churn across STICKY → BACKGROUND →
    FLASH. Whether a BACKGROUND overlay is actually rendered is decided
    by the view computation, which filters it out of the on-screen view
    (it shows only in the status-bar progress wheel).
    """
    ns = _load_notifications(monkeypatch)
    state = _init_state(ns)

    result = ns.reducer(
        state,
        ns.NotificationsAddAction(
            notification=ns.Notification(
                id='dl',
                title='Downloading',
                content='',
                display_type=ns.NotificationDisplayType.BACKGROUND,
                progress=0.5,
            ),
        ),
    )
    actions = _actions_of(result)
    assert any(
        isinstance(a, ns.StackPushNotificationAction)
        and getattr(a, 'notification_id', None) == 'dl'
        for a in actions
    )
    assert not any(isinstance(a, ns.StackPopNotificationAction) for a in actions)


def test_flash_notification_pushes_onto_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A FLASH notification add returns a push action for its id.

    The terminal 'download complete' notification must land on the stack
    even though the immediately-preceding BACKGROUND updates returned
    pops — because reducer-returned actions are processed strictly in
    order, the final push wins.
    """
    ns = _load_notifications(monkeypatch)
    state = _init_state(ns)

    result = ns.reducer(
        state,
        ns.NotificationsAddAction(
            notification=ns.Notification(
                id='dl',
                title='Download Complete',
                content='',
                display_type=ns.NotificationDisplayType.FLASH,
            ),
        ),
    )
    actions = _actions_of(result)
    assert any(
        isinstance(a, ns.StackPushNotificationAction)
        and getattr(a, 'notification_id', None) == 'dl'
        for a in actions
    )


def test_clear_notification_pops_from_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clearing a notification returns a pop action so its overlay closes."""
    from redux import CompleteReducerResult

    ns = _load_notifications(monkeypatch)
    state = _init_state(ns)
    notification = ns.Notification(id='dl', title='x', content='')
    add_result = ns.reducer(
        state,
        ns.NotificationsAddAction(notification=notification),
    )
    assert isinstance(add_result, CompleteReducerResult)
    state = add_result.state

    result = ns.reducer(state, ns.NotificationsClearAction(notification=notification))
    actions = _actions_of(result)
    assert any(
        isinstance(a, ns.StackPopNotificationAction)
        and getattr(a, 'notification_id', None) == 'dl'
        for a in actions
    )


def test_clear_by_id_pops_from_stack(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clearing a notification by id returns a pop action for that id."""
    ns = _load_notifications(monkeypatch)
    state = _init_state(ns)

    result = ns.reducer(state, ns.NotificationsClearByIdAction(id='dl'))
    actions = _actions_of(result)
    assert any(
        isinstance(a, ns.StackPopNotificationAction)
        and getattr(a, 'notification_id', None) == 'dl'
        for a in actions
    )


def test_is_background_notification_filters_overlay_visibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_is_background_notification`` decides which overlays the view skips.

    The push/pop churn is gone — a notification's stack item stays put
    its whole lifecycle — so this predicate is what makes
    STICKY → BACKGROUND → FLASH actually change what's on screen.
    """
    ns = _load_notifications(monkeypatch)

    state = SimpleNamespace(
        notifications=SimpleNamespace(
            notifications=[
                ns.Notification(
                    id='bg',
                    title='x',
                    content='',
                    display_type=ns.NotificationDisplayType.BACKGROUND,
                ),
                ns.Notification(
                    id='sticky',
                    title='x',
                    content='',
                    display_type=ns.NotificationDisplayType.STICKY,
                ),
                ns.Notification(
                    id='flash',
                    title='x',
                    content='',
                    display_type=ns.NotificationDisplayType.FLASH,
                ),
            ],
        ),
    )

    # BACKGROUND overlay → filtered out of the on-screen view.
    assert ns.is_background_notification(
        state,
        ns.NotificationStackItem(id='i1', notification_id='bg'),
    )
    # STICKY / FLASH overlays own the screen → not filtered.
    assert not ns.is_background_notification(
        state,
        ns.NotificationStackItem(id='i2', notification_id='sticky'),
    )
    assert not ns.is_background_notification(
        state,
        ns.NotificationStackItem(id='i3', notification_id='flash'),
    )
    # A stack item whose notification was already cleared is mid-dismissal
    # → filtered out.
    assert ns.is_background_notification(
        state,
        ns.NotificationStackItem(id='i4', notification_id='gone'),
    )
    # Non-notification stack items are never filtered.
    assert not ns.is_background_notification(
        state,
        ns.MenuStackItem(id='i5', menu_key='whatever'),
    )
