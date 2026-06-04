"""Regression tests for dismissing one of several stacked notifications.

User report: with two **sticky** notifications stacked, dismissing one also
dismissed the other.

The notifications service's dismiss handler
(``ubo_app/services/010-notifications/ubo_handle.py`` →
``_create_dismiss_handler.dismiss``) historically did *two* things:

1. ``store.dispatch(StackPopAction())`` — pops whatever is on **top** of the
   navigation stack, regardless of which notification is being dismissed.
2. ``store.dispatch(NotificationsClearAction(notification))`` — the
   notifications reducer already returns
   ``StackPopNotificationAction(notification_id=…)`` for this, popping the
   *correct* notification overlay by id.

Step 1 is therefore redundant, and when the dismissed notification is **not**
the current top of the stack it pops a *second, wrong* notification — the
double-dismiss.

These tests replay the exact dispatch *sequence* that handler emits against the
real ``stack_ops`` pure functions and the real notifications reducer, proving:

* the keyed pop alone (the fix) removes only the targeted notification, and
* the extra blind ``StackPopAction`` removes a second one when the target is
  not on top.

Class-identity discipline mirrors ``test_notification_stack_reconciliation.py``:
integration tests earlier in the suite wipe ``sys.modules``, so every class is
pulled from a freshly-reloaded module generation and the reducer/``stack_ops``
close over those same objects.
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

    from ubo_app.store.core.types import MainState
    from ubo_app.store.services.notifications import NotificationsState


SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/010-notifications'


def _load(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Load the notifications reducer + ``stack_ops`` + the classes they use.

    ``core.types`` is reloaded first so ``stack_ops`` (reloaded next) and the
    service reducer (``exec_module``-d last) bind their ``isinstance`` / match
    checks to the *same* ``NotificationStackItem`` etc. that this test
    constructs.
    """
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())

    from ubo_app.store.core import stack_ops, view_computation
    from ubo_app.store.core import types as core_types
    from ubo_app.store.services import notifications as notifications_module

    core_types = importlib.reload(core_types)
    notifications_module = importlib.reload(notifications_module)
    view_computation = importlib.reload(view_computation)
    stack_ops = importlib.reload(stack_ops)

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
        NotificationDisplayType=notifications_module.NotificationDisplayType,
        NotificationsAddAction=notifications_module.NotificationsAddAction,
        NotificationsClearAction=notifications_module.NotificationsClearAction,
        # store/core/types
        MainState=core_types.MainState,
        MenuStackItem=core_types.MenuStackItem,
        NotificationStackItem=core_types.NotificationStackItem,
        StackPopNotificationAction=core_types.StackPopNotificationAction,
        # store/core/stack_ops
        pop_stack=stack_ops.pop_stack,
        pop_notification=stack_ops.pop_notification,
    )


def _init_notifications_state(ns: SimpleNamespace) -> NotificationsState:
    init_action_type = cast(
        'type[BaseAction]',
        ns.reducer.__globals__['InitAction'],
    )
    return cast('NotificationsState', ns.reducer(None, init_action_type()))


def _sticky(ns: SimpleNamespace, notification_id: str) -> object:
    return ns.Notification(
        id=notification_id,
        title=notification_id,
        content='',
        display_type=ns.NotificationDisplayType.STICKY,
    )


def _two_sticky_setup(
    ns: SimpleNamespace,
) -> tuple[MainState, NotificationsState]:
    """Two stacked stickies: stack ``[root, A, B]`` (B on top), list ``[B, A]``.

    Mirrors production ordering: ``NotificationsAddAction`` prepends to the
    list (newest first) while the stack item is appended (newest on top).
    """
    root = ns.MenuStackItem(id='root', menu_key='')
    main_state = ns.MainState(
        stack=(
            root,
            ns.NotificationStackItem(id='item-A', notification_id='notif-A'),
            ns.NotificationStackItem(id='item-B', notification_id='notif-B'),
        ),
    )

    notif_state = _init_notifications_state(ns)
    notif_state = ns.reducer(
        notif_state,
        ns.NotificationsAddAction(notification=_sticky(ns, 'notif-A')),
    ).state
    notif_state = ns.reducer(
        notif_state,
        ns.NotificationsAddAction(notification=_sticky(ns, 'notif-B')),
    ).state
    return main_state, notif_state


def _by_id(notif_state: NotificationsState, notification_id: str) -> object:
    """Return the live ``Notification`` instance (identity matters to clear)."""
    return next(n for n in notif_state.notifications if n.id == notification_id)


def _notification_ids_on_stack(main_state: MainState) -> set[str]:
    # Only ``NotificationStackItem`` carries ``notification_id``; duck-typing
    # keeps this independent of the reloaded class generation.
    return {
        nid
        for item in main_state.stack
        if (nid := getattr(item, 'notification_id', None)) is not None
    }


def _dismiss(
    ns: SimpleNamespace,
    main_state: MainState,
    notif_state: NotificationsState,
    target: object,
    *,
    blind_pop: bool,
) -> tuple[MainState, NotificationsState]:
    """Replay the dispatch sequence emitted by ``dismiss()`` for *target*.

    ``blind_pop=True`` reproduces the legacy handler (extra
    ``StackPopAction()`` that pops the stack top); ``blind_pop=False`` is the
    fixed handler that relies solely on ``NotificationsClearAction``'s
    id-keyed pop.
    """
    if blind_pop:
        # StackPopAction() → pop_stack(state, 1): pops the top item.
        popped = ns.pop_stack(main_state, 1)
        if popped is not None:
            main_state = popped

    # NotificationsClearAction(target) → reducer removes it from the list and
    # returns StackPopNotificationAction(notification_id=target.id).
    result = ns.reducer(notif_state, ns.NotificationsClearAction(notification=target))
    notif_state = result.state
    for action in result.actions or []:
        if isinstance(action, ns.StackPopNotificationAction):
            popped = ns.pop_notification(main_state, action.notification_id)
            if popped is not None:
                main_state = popped
    return main_state, notif_state


def test_dismiss_top_keeps_other(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dismissing the **top** sticky leaves the one underneath untouched.

    This is the keypad path's situation (it always targets ``stack[-1]``), and
    even the legacy blind pop is harmless here: it pops the top (the target)
    and the keyed clear is then a no-op.
    """
    ns = _load(monkeypatch)
    main_state, notif_state = _two_sticky_setup(ns)
    top = _by_id(notif_state, 'notif-B')

    main_state, notif_state = _dismiss(ns, main_state, notif_state, top, blind_pop=True)

    assert _notification_ids_on_stack(main_state) == {'notif-A'}
    assert [n.id for n in notif_state.notifications] == ['notif-A']


def test_blind_pop_dismisses_wrong_notification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy handler: dismissing a **non-top** sticky also drops the top one.

    Reproduces the reported bug. ``StackPopAction()`` pops B (the top) while
    the keyed clear pops A — both overlays vanish from the stack.
    """
    ns = _load(monkeypatch)
    main_state, notif_state = _two_sticky_setup(ns)
    non_top = _by_id(notif_state, 'notif-A')

    main_state, notif_state = _dismiss(
        ns,
        main_state,
        notif_state,
        non_top,
        blind_pop=True,
    )

    # Bug: B's overlay was popped too, even though A was dismissed.
    assert _notification_ids_on_stack(main_state) == set()
    # A is correctly gone from the list, but B's overlay is orphaned off-stack.
    assert [n.id for n in notif_state.notifications] == ['notif-B']


def test_keyed_pop_only_preserves_other(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fixed handler: dismissing a non-top sticky keeps the other on the stack.

    Without the blind ``StackPopAction()`` the keyed clear removes only A's
    overlay; B's overlay stays on the stack and B stays in the list.
    """
    ns = _load(monkeypatch)
    main_state, notif_state = _two_sticky_setup(ns)
    non_top = _by_id(notif_state, 'notif-A')

    main_state, notif_state = _dismiss(
        ns,
        main_state,
        notif_state,
        non_top,
        blind_pop=False,
    )

    assert _notification_ids_on_stack(main_state) == {'notif-B'}
    assert [n.id for n in notif_state.notifications] == ['notif-B']
