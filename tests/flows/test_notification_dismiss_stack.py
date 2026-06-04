"""End-to-end flow tests for dismissing one of several stacked notifications.

Regression guard for the reported bug: with notifications stacked, dismissing
one also dismissed another stacked under it. Each scenario runs against a
really-booted app (notifications + keypad services, dispatch over gRPC) and
asserts the survivor stays in the notifications list *and* on the stack.

* ``test_dismiss_top_via_keypad_keeps_stacked_one`` — the user's gesture: press
  the dismiss (X) on the visible top notification via the hardware keypad; the
  stacked one underneath must stay.
* ``test_dismiss_visible_sticky_with_background_on_top`` — the fresh-boot bug:
  a BACKGROUND notification (a model download's progress) is the raw stack top
  but is filtered out of the view, so the visible notification is the STICKY
  underneath. The keypad dismiss must target the *visible* STICKY — the core
  used to route the press to the hidden BACKGROUND overlay (raw ``stack[-1]``),
  dismissing the wrong notification while the GUI dismissed the visible one.
* ``test_dismiss_non_top_via_action_keeps_stacked_one`` — a remote client (web
  UI / TUI notifications center) dismissing a notification that is **not** the
  top of the stack, via ``ExecuteMenuActionAction('notification:dismiss:…')``.
  The registry dismiss handler used to blind-pop the stack top in addition to
  clearing the targeted notification by id.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from redux_pytest.fixtures import StoreSnapshot, WaitFor

    from tests.fixtures import (
        AppContext,
        Dispatcher,
        LoadServices,
        Stability,
    )
    from tests.fixtures.load_services import AsyncUnloadWaiter
    from tests.fixtures.snapshot import WindowSnapshot
    from ubo_app.store.main import RootState


def _notification_ids_on_stack(state: RootState) -> set[str]:
    from ubo_app.store.core.types import NotificationStackItem

    return {
        item.notification_id
        for item in state.main.stack
        if isinstance(item, NotificationStackItem)
    }


def _notification_ids_in_list(state: RootState) -> list[str]:
    return [n.id for n in state.notifications.notifications]


def _normalize_notifications(state: RootState) -> dict[str, Any]:
    """Select notification + stack state with timestamps normalized.

    Captures everything the dismiss bug touches — which notifications remain in
    the list, which overlays remain on the navigation stack (in order), and the
    on-screen view type — while zeroing the non-deterministic timestamps so the
    store snapshot is stable.
    """
    from ubo_app.store.core.types import NotificationStackItem

    notifications_state = state.notifications
    return {
        'notifications': [
            replace(n, timestamp=0, expiration_timestamp=None)
            for n in notifications_state.notifications
        ],
        'unread_count': notifications_state.unread_count,
        'progress': notifications_state.progress,
        'current_view_type': type(state.main.current_view).__name__,
        'notification_ids_on_stack': [
            item.notification_id
            for item in state.main.stack
            if isinstance(item, NotificationStackItem)
        ],
    }


async def _boot(
    app_context: AppContext,
    load_services: LoadServices,
    wait_for: WaitFor,
) -> AsyncUnloadWaiter:
    from tenacity import wait_fixed

    from ubo_app.store.main import store

    app_context.set_app()
    unload_waiter = await load_services(['keypad', 'notifications'], run_async=True)

    @wait_for(run_async=True, wait=wait_fixed(1))
    def stack_is_loaded() -> None:
        state = store._state  # noqa: SLF001
        assert state is not None
        assert len(state.main.stack) > 0

    await stack_is_loaded()
    return unload_waiter


async def _add_two_stickies(
    stability: Stability,
    first_id: str,
    second_id: str,
) -> None:
    """Add two sticky notifications; ``second_id`` ends up on top of the stack."""
    from ubo_app.store.main import store
    from ubo_app.store.services.notifications import (
        Notification,
        NotificationDisplayType,
        NotificationsAddAction,
    )

    for notification_id, title in ((first_id, 'First'), (second_id, 'Second')):
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id=notification_id,
                    title=title,
                    content='Stacked notification.',
                    display_type=NotificationDisplayType.STICKY,
                    show_dismiss_action=True,
                    blink=False,
                ),
            ),
        )
        await stability(initial_wait=2)


@pytest.mark.timeout(200)
async def test_dismiss_top_via_keypad_keeps_stacked_one(
    app_context: AppContext,
    window_snapshot: WindowSnapshot,
    store_snapshot: StoreSnapshot[RootState],
    load_services: LoadServices,
    stability: Stability,
    wait_for: WaitFor,
    dispatcher: Dispatcher,
) -> None:
    """Pressing dismiss on the visible top sticky keeps the one underneath."""
    from tests.fixtures.dispatch import GRPC_KEYPAD
    from ubo_app.store.main import store

    def snap(title: str) -> None:
        window_snapshot.take(title=title)
        store_snapshot.take(selector=_normalize_notifications)

    unload_waiter = await _boot(app_context, load_services, wait_for)

    first_id = 'dismiss-stack:first'
    second_id = 'dismiss-stack:second'
    await _add_two_stickies(stability, first_id, second_id)
    # Screen shows the second (top) sticky.
    snap('01-both-stacked')

    # ``second`` is on top → it's the one rendered. Press its dismiss (X) icon
    # via the real keypad path.
    await dispatcher.choose_by_icon('', via=GRPC_KEYPAD)
    await stability(initial_wait=2)

    # Screen now shows the first sticky, revealed underneath.
    snap('02-after-dismiss')

    state = store._state  # noqa: SLF001
    assert state is not None
    assert _notification_ids_in_list(state) == [first_id]
    assert _notification_ids_on_stack(state) == {first_id}

    await unload_waiter()


@pytest.mark.timeout(200)
async def test_dismiss_visible_sticky_with_background_on_top(
    app_context: AppContext,
    window_snapshot: WindowSnapshot,
    store_snapshot: StoreSnapshot[RootState],
    load_services: LoadServices,
    stability: Stability,
    wait_for: WaitFor,
    dispatcher: Dispatcher,
) -> None:
    """A keypad dismiss must target the *visible* notification.

    Reproduces the reported fresh-boot bug: a BACKGROUND notification (a model
    download's progress) lands on top of the navigation stack but is filtered
    out of the on-screen view (it only shows in the status-bar wheel), so the
    visible notification is the STICKY underneath it. Pressing dismiss must
    remove the visible STICKY — the core must not route the press to the hidden
    BACKGROUND overlay (the raw stack top).
    """
    from ubo_app.store.main import store
    from ubo_app.store.services.notifications import (
        Notification,
        NotificationDisplayType,
        NotificationsAddAction,
    )

    def snap(title: str) -> None:
        window_snapshot.take(title=title)
        store_snapshot.take(selector=_normalize_notifications)

    unload_waiter = await _boot(app_context, load_services, wait_for)

    sticky_id = 'dismiss-bg:sticky'
    background_id = 'dismiss-bg:background'

    # Visible STICKY first…
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=sticky_id,
                title='WiFi',
                content='Set up WiFi.',
                display_type=NotificationDisplayType.STICKY,
                show_dismiss_action=True,
                blink=False,
            ),
        ),
    )
    await stability(initial_wait=2)
    # …then a BACKGROUND progress notification that lands on top of the stack
    # but is filtered out of the view (status-bar wheel only).
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=background_id,
                title='Downloading',
                content='Model download in progress.',
                display_type=NotificationDisplayType.BACKGROUND,
                progress=0.5,
                show_dismiss_action=True,
                blink=False,
            ),
        ),
    )
    await stability(initial_wait=2)
    # Screen shows the WiFi STICKY; the BACKGROUND download is only the
    # status-bar progress wheel.
    snap('01-sticky-visible-background-hidden')

    # The view shows the STICKY (single item → dismiss is bottom-aligned at
    # L3). Press it via the real keypad.
    from ubo_app.store.services.keypad import Key

    await dispatcher.send_key(Key.L3)
    await stability(initial_wait=2)
    # The visible STICKY is gone; the BACKGROUND download remains (status bar).
    snap('02-after-dismiss')

    state = store._state  # noqa: SLF001
    assert state is not None
    ids = _notification_ids_in_list(state)
    # The visible STICKY must be the one dismissed; the BACKGROUND survives.
    assert sticky_id not in ids
    assert background_id in ids
    assert background_id in _notification_ids_on_stack(state)

    await unload_waiter()


@pytest.mark.timeout(200)
async def test_dismiss_non_top_via_action_keeps_stacked_one(
    app_context: AppContext,
    window_snapshot: WindowSnapshot,
    store_snapshot: StoreSnapshot[RootState],
    load_services: LoadServices,
    stability: Stability,
    wait_for: WaitFor,
    dispatcher: Dispatcher,
) -> None:
    """Dismissing a non-top notification by id must not drop the top one.

    Reproduces the bug's trigger: a client dismisses a notification that is not
    the current stack top via the action-registry path. The legacy handler
    blind-popped the stack top here, dismissing a second notification.
    """
    from tests.fixtures.dispatch import _dispatch_via_grpc
    from ubo_app.store.core.constants import NOTIFICATION_DISMISS_PREFIX
    from ubo_app.store.core.types import ExecuteMenuActionAction
    from ubo_app.store.main import store

    def snap(title: str) -> None:
        window_snapshot.take(title=title)
        store_snapshot.take(selector=_normalize_notifications)

    unload_waiter = await _boot(app_context, load_services, wait_for)

    bottom_id = 'dismiss-stack:bottom'
    top_id = 'dismiss-stack:top'
    await _add_two_stickies(stability, bottom_id, top_id)
    # Screen shows the top sticky.
    snap('01-both-stacked')

    stub = dispatcher.stub
    assert stub is not None
    await _dispatch_via_grpc(
        stub,
        ExecuteMenuActionAction(
            action_id=f'{NOTIFICATION_DISMISS_PREFIX}{bottom_id}',
        ),
    )
    await stability(initial_wait=2)
    # The non-top was dismissed by id; the top sticky is still on screen.
    snap('02-after-dismiss')

    state = store._state  # noqa: SLF001
    assert state is not None
    # The top notification must survive — both in the list and on the stack.
    assert top_id in _notification_ids_in_list(state)
    assert bottom_id not in _notification_ids_in_list(state)
    assert _notification_ids_on_stack(state) == {top_id}

    await unload_waiter()
