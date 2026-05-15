"""Tests for the notifications reducer reconciling the navigation stack.

Stack push/pop for notifications is returned from the reducer (on the
ordered action queue) rather than from a ``NotificationsDisplayEvent``
handler — event handlers run in concurrent worker threads, so deciding
stack membership there raced and made the first STICKY / terminal FLASH
notification of a download flow vanish.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from ubo_app.store.core.types import (
    StackPopNotificationAction,
    StackPushNotificationAction,
)
from ubo_app.store.services.notifications import (
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
    NotificationsClearAction,
    NotificationsClearByIdAction,
    NotificationsState,
)

if TYPE_CHECKING:
    import pytest
    from redux import BaseAction, CompleteReducerResult

    from ubo_app.store.main import RootState

SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/010-notifications'


class NotificationsReducer(Protocol):
    """Protocol for the notifications reducer."""

    __globals__: dict[str, type[BaseAction]]

    def __call__(
        self,
        state: NotificationsState | None,
        action: BaseAction,
    ) -> NotificationsState | CompleteReducerResult:
        """Reduce a notifications state with one action."""
        ...


def _load_notifications_reducer(
    monkeypatch: pytest.MonkeyPatch,
) -> NotificationsReducer:
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())
    spec = importlib.util.spec_from_file_location(
        'notifications_service_reducer',
        SERVICE_PATH / 'reducer.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast('NotificationsReducer', module.reducer)


def _init_state(reducer: NotificationsReducer) -> NotificationsState:
    init_action_type = cast('type[BaseAction]', reducer.__globals__['InitAction'])
    return cast('NotificationsState', reducer(None, init_action_type()))


def _actions_of(result: object) -> list[object]:
    return list(getattr(result, 'actions', None) or [])


def test_sticky_notification_pushes_onto_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A STICKY notification add returns a push action for its id."""
    reducer = _load_notifications_reducer(monkeypatch)
    state = _init_state(reducer)

    result = reducer(
        state,
        NotificationsAddAction(
            notification=Notification(
                id='dl',
                title='Downloading',
                content='',
                display_type=NotificationDisplayType.STICKY,
            ),
        ),
    )
    actions = _actions_of(result)
    assert any(
        isinstance(a, StackPushNotificationAction) and a.notification_id == 'dl'
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
    reducer = _load_notifications_reducer(monkeypatch)
    state = _init_state(reducer)

    result = reducer(
        state,
        NotificationsAddAction(
            notification=Notification(
                id='dl',
                title='Downloading',
                content='',
                display_type=NotificationDisplayType.BACKGROUND,
                progress=0.5,
            ),
        ),
    )
    actions = _actions_of(result)
    assert any(
        isinstance(a, StackPushNotificationAction) and a.notification_id == 'dl'
        for a in actions
    )
    assert not any(isinstance(a, StackPopNotificationAction) for a in actions)


def test_flash_notification_pushes_onto_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A FLASH notification add returns a push action for its id.

    The terminal 'download complete' notification must land on the stack
    even though the immediately-preceding BACKGROUND updates returned
    pops — because reducer-returned actions are processed strictly in
    order, the final push wins.
    """
    reducer = _load_notifications_reducer(monkeypatch)
    state = _init_state(reducer)

    result = reducer(
        state,
        NotificationsAddAction(
            notification=Notification(
                id='dl',
                title='Download Complete',
                content='',
                display_type=NotificationDisplayType.FLASH,
            ),
        ),
    )
    actions = _actions_of(result)
    assert any(
        isinstance(a, StackPushNotificationAction) and a.notification_id == 'dl'
        for a in actions
    )


def test_clear_notification_pops_from_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clearing a notification returns a pop action so its overlay closes."""
    from redux import CompleteReducerResult

    reducer = _load_notifications_reducer(monkeypatch)
    state = _init_state(reducer)
    notification = Notification(id='dl', title='x', content='')
    add_result = reducer(
        state,
        NotificationsAddAction(notification=notification),
    )
    assert isinstance(add_result, CompleteReducerResult)
    state = cast('NotificationsState', add_result.state)

    result = reducer(state, NotificationsClearAction(notification=notification))
    actions = _actions_of(result)
    assert any(
        isinstance(a, StackPopNotificationAction) and a.notification_id == 'dl'
        for a in actions
    )


def test_clear_by_id_pops_from_stack(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clearing a notification by id returns a pop action for that id."""
    reducer = _load_notifications_reducer(monkeypatch)
    state = _init_state(reducer)

    result = reducer(state, NotificationsClearByIdAction(id='dl'))
    actions = _actions_of(result)
    assert any(
        isinstance(a, StackPopNotificationAction) and a.notification_id == 'dl'
        for a in actions
    )


def test_is_background_notification_filters_overlay_visibility() -> None:
    """``_is_background_notification`` decides which overlays the view skips.

    The push/pop churn is gone — a notification's stack item stays put
    its whole lifecycle — so this predicate is what makes
    STICKY → BACKGROUND → FLASH actually change what's on screen.
    """
    from types import SimpleNamespace

    from ubo_app.store.core.types import MenuStackItem, NotificationStackItem
    from ubo_app.store.core.view_computation import _is_background_notification

    state = cast(
        'RootState',
        SimpleNamespace(
            notifications=SimpleNamespace(
                notifications=[
                    Notification(
                        id='bg',
                        title='x',
                        content='',
                        display_type=NotificationDisplayType.BACKGROUND,
                    ),
                    Notification(
                        id='sticky',
                        title='x',
                        content='',
                        display_type=NotificationDisplayType.STICKY,
                    ),
                    Notification(
                        id='flash',
                        title='x',
                        content='',
                        display_type=NotificationDisplayType.FLASH,
                    ),
                ],
            ),
        ),
    )

    # BACKGROUND overlay → filtered out of the on-screen view.
    assert _is_background_notification(
        state,
        NotificationStackItem(id='i1', notification_id='bg'),
    )
    # STICKY / FLASH overlays own the screen → not filtered.
    assert not _is_background_notification(
        state,
        NotificationStackItem(id='i2', notification_id='sticky'),
    )
    assert not _is_background_notification(
        state,
        NotificationStackItem(id='i3', notification_id='flash'),
    )
    # A stack item whose notification was already cleared is mid-dismissal
    # → filtered out.
    assert _is_background_notification(
        state,
        NotificationStackItem(id='i4', notification_id='gone'),
    )
    # Non-notification stack items are never filtered.
    assert not _is_background_notification(
        state,
        MenuStackItem(id='i5', menu_key='whatever'),
    )
