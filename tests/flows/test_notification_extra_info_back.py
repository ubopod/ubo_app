"""End-to-end flow test for the notification extra-information page BACK.

Regression guard for the reported bug: opening a notification's ⓘ
(extra-information / instructions) page and pressing BACK *dismissed* the
parent notification instead of revealing it again. The instructions page lives
only on the GUI client's local Kivy stack, so the physical-keypad BACK reached
the core and popped the ``NotificationStackItem`` underneath it.

The fix delegates that BACK to the GUI: ``open_info`` sets ``is_local_overlay_open``
(``SetLocalOverlayOpenAction``) and the core, on BACK while the flag is set,
emits ``LocalOverlayGoBackEvent`` instead of popping — the GUI client closes its
local page and the notification stays. This runs against a really-booted app
(notifications + keypad services, real GUI-client subprocess, dispatch over
gRPC) so it exercises both halves of the fix end to end.
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

# Notification action icons (see ``view_computation.py``).
_INFO_ICON = '\U000f02fc'
_DISMISS_ICON = ''

_NOTIFICATION_ID = 'extra-info-back:notif'


def _notification_ids_on_stack(state: RootState) -> set[str]:
    from ubo_app.store.core.types import NotificationStackItem

    return {
        item.notification_id
        for item in state.main.stack
        if isinstance(item, NotificationStackItem)
    }


def _notification_ids_in_list(state: RootState) -> list[str]:
    return [n.id for n in state.notifications.notifications]


def _normalize(state: RootState) -> dict[str, Any]:
    """Select notification + stack state with timestamps normalized."""
    from ubo_app.store.core.types import NotificationStackItem

    notifications_state = state.notifications
    return {
        'notifications': [
            replace(n, timestamp=0, expiration_timestamp=None)
            for n in notifications_state.notifications
        ],
        'current_view_type': type(state.main.current_view).__name__,
        'is_local_overlay_open': state.main.is_local_overlay_open,
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


@pytest.mark.timeout(200)
async def test_back_from_info_page_keeps_notification(
    app_context: AppContext,
    window_snapshot: WindowSnapshot,
    store_snapshot: StoreSnapshot[RootState],
    load_services: LoadServices,
    stability: Stability,
    wait_for: WaitFor,
    dispatcher: Dispatcher,
) -> None:
    """ⓘ → BACK reveals the notification again; it is not dismissed."""
    from tests.fixtures.dispatch import GRPC_KEYPAD
    from ubo_app.store.core.types import OpenRenderAction
    from ubo_app.store.main import store
    from ubo_app.store.services.notifications import (
        Notification,
        NotificationDispatchItem,
        NotificationDisplayType,
        NotificationsAddAction,
    )
    from ubo_app.store.services.speech_synthesis import ReadableInformation

    def snap(title: str) -> None:
        window_snapshot.take(title=title)
        store_snapshot.take(selector=_normalize)

    unload_waiter = await _boot(app_context, load_services, wait_for)

    # Mirror the real WiFi-hotspot notification: three buttons — extra-info (ⓘ),
    # a QR action, and dismiss — since the bug was reported on that exact layout.
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=_NOTIFICATION_ID,
                title='Hotspot',
                content='Connect to the hotspot.',
                extra_information=ReadableInformation(
                    text='Join the WiFi network shown, then open the page.',
                ),
                actions=[
                    NotificationDispatchItem(
                        key='hotspot-qr',
                        label='WiFi QR',
                        icon='\U000f0432',
                        store_action=OpenRenderAction(
                            kind='qr_code',
                            title='WiFi QR',
                            props={'value': 'WIFI:S:ubo;T:WPA;P:secret;;'},
                        ),
                        close_notification=False,
                    ),
                ],
                display_type=NotificationDisplayType.STICKY,
                show_dismiss_action=True,
                blink=False,
            ),
        ),
    )
    await stability(initial_wait=2)
    # Screen shows the notification with its ⓘ + dismiss buttons.
    snap('01-notification')

    # Press the ⓘ button via the real keypad → opens the local instructions
    # page (GUI-client widget) and sets is_local_overlay_open on the core.
    await dispatcher.choose_by_icon(_INFO_ICON, via=GRPC_KEYPAD)
    await stability(initial_wait=2)
    # Screen shows the extra-information / instructions page.
    snap('02-info-page')

    state = store._state  # noqa: SLF001
    assert state is not None
    assert state.main.is_local_overlay_open is True

    # Press BACK via the real keypad → core delegates to the GUI, which closes
    # the local page; the notification must NOT be dismissed.
    await dispatcher.go_back(via=GRPC_KEYPAD)
    await stability(initial_wait=2)
    # Screen shows the notification again (revealed, not dismissed).
    snap('03-back-to-notification')

    state = store._state  # noqa: SLF001
    assert state is not None
    assert _NOTIFICATION_ID in _notification_ids_in_list(state)
    assert _NOTIFICATION_ID in _notification_ids_on_stack(state)
    assert state.main.is_local_overlay_open is False

    # Tear-down / back-out: dismiss the notification to return to a known state.
    await dispatcher.choose_by_icon(_DISMISS_ICON, via=GRPC_KEYPAD)
    await stability(initial_wait=2)
    snap('04-dismissed')

    state = store._state  # noqa: SLF001
    assert state is not None
    assert _NOTIFICATION_ID not in _notification_ids_in_list(state)
    assert _NOTIFICATION_ID not in _notification_ids_on_stack(state)

    await unload_waiter()
