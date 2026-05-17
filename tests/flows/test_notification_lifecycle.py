"""Standalone notification lifecycle test harness.

Boots a minimal app (the ``notifications`` service only) and dispatches
controlled, deterministic sequences of notifications, capturing window +
store snapshots at critical moments.

Phase 1: run locally with ``--override-window-snapshots --make-screenshots
--override-store-snapshots`` to produce reviewable PNG screenshots under
``tests/flows/results/test_notification_lifecycle/``.
Phase 2 (follow-up): run in Docker for consistent rendering, generate hash
baselines, and assert them in CI.

The file is structured to host a *mix* of scenarios — each scenario is a
separate ``test_*`` function that calls :func:`_boot_minimal_app` first.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from redux_pytest.fixtures import StoreSnapshot, WaitFor

    from tests.fixtures import (
        AppContext,
        LoadServices,
        Stability,
    )
    from tests.fixtures.load_services import AsyncUnloadWaiter
    from tests.fixtures.snapshot import WindowSnapshot
    from ubo_app.store.main import RootState


def _normalize_notifications(state: RootState) -> dict[str, Any]:
    """Select notification state with timestamps normalized for snapshots."""
    notifications_state = state.notifications
    normalized = [
        replace(n, timestamp=0, expiration_timestamp=None)
        for n in notifications_state.notifications
    ]
    current_view = state.main.current_view
    return {
        'notifications': normalized,
        'unread_count': notifications_state.unread_count,
        'progress': notifications_state.progress,
        # Diagnostic: what the core computed as the on-screen view.
        'current_view_type': type(current_view).__name__,
        'current_view_id': (
            getattr(current_view, 'notification_id', None)
            or getattr(current_view, 'title', None)
            or ''
        ),
        'stack': [type(item).__name__ for item in state.main.stack],
    }


async def _boot_minimal_app(
    app_context: AppContext,
    load_services: LoadServices,
    wait_for: WaitFor,
) -> AsyncUnloadWaiter:
    """Boot the app with only the notifications service; wait until ready.

    Shared harness for every scenario in this file. Returns the
    ``unload_waiter`` the scenario must ``await`` at the end.
    """
    from tenacity import wait_fixed

    from ubo_app.store.main import store

    app_context.set_app()
    unload_waiter = await load_services(['notifications'], run_async=True)

    @wait_for(run_async=True, wait=wait_fixed(1))
    def stack_is_loaded() -> None:
        state = store._state  # noqa: SLF001
        assert state is not None
        assert len(state.main.stack) > 0

    await stack_is_loaded()
    return unload_waiter


@pytest.mark.timeout(200)
async def test_three_distinct_notifications(
    app_context: AppContext,
    window_snapshot: WindowSnapshot,
    store_snapshot: StoreSnapshot[RootState],
    load_services: LoadServices,
    stability: Stability,
    wait_for: WaitFor,
) -> None:
    """Sticky + concurrent background-progress, then flash.

    Three distinct notification ids. The STICKY is dispatched first and is
    NOT cleared when the BACKGROUND progress notification is dispatched —
    they coexist: the sticky keeps owning the screen while the background
    notification's progress wheel renders in the status bar over it. Both
    are cleared before the terminal FLASH. Captures a window + store
    snapshot at eight moments.
    """
    from ubo_app.store.main import store
    from ubo_app.store.services.notifications import (
        Notification,
        NotificationDisplayType,
        NotificationsAddAction,
        NotificationsClearByIdAction,
    )

    unload_waiter = await _boot_minimal_app(app_context, load_services, wait_for)

    def snap(title: str) -> None:
        window_snapshot.take(title=title)
        store_snapshot.take(selector=_normalize_notifications)

    sticky_id = 'lifecycle-test:sticky'
    progress_id = 'lifecycle-test:progress'
    flash_id = 'lifecycle-test:flash'

    # --- Stage 1: STICKY — takes over the screen -------------------------
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=sticky_id,
                title='Sticky Notification',
                content='This sticky notification owns the screen.',
                display_type=NotificationDisplayType.STICKY,
                blink=False,
            ),
        ),
    )
    await stability(initial_wait=4)
    snap('01-sticky')

    # --- Stage 2: BACKGROUND — concurrent with the still-showing STICKY -
    # The STICKY is intentionally NOT cleared. The BACKGROUND notification
    # is filtered out of the main view (so the STICKY keeps owning the
    # screen), but its progress wheel renders in the status bar over the
    # sticky. Discrete, exact progress values keep snapshots deterministic.
    for value, title in (
        (0.0, '02-progress-000'),
        (0.25, '03-progress-025'),
        (0.5, '04-progress-050'),
        (0.75, '05-progress-075'),
        (1.0, '06-progress-100'),
    ):
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id=progress_id,
                    title='Downloading',
                    content='Mock download in progress.',
                    display_type=NotificationDisplayType.BACKGROUND,
                    progress=value,
                    blink=False,
                ),
            ),
        )
        # `stability()` cannot be used here: the status-bar progress wheel
        # changes every dispatch so the screen never settles. Use a fixed
        # wait instead — ~1s per step ≈ 5s total for the whole download.
        await asyncio.sleep(1.0)
        snap(title)

    # --- Stage 3: FLASH — dispatched ON TOP of the still-present sticky +
    # background. The FLASH owns the screen (covers the sticky); the
    # background notification stays in the list so its progress wheel
    # remains in the status bar. The sticky/background are intentionally
    # NOT cleared first: clearing the sticky here would briefly drop the
    # view to the home screen, and that extra notification→home→
    # notification hop piles up in the gui-client's animated-transition
    # queue so the FLASH fails to render. Going sticky→flash directly is
    # a single clean transition.
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=flash_id,
                title='Download Complete',
                content='This flash notification auto-dismisses.',
                display_type=NotificationDisplayType.FLASH,
                flash_time=5,
                blink=False,
            ),
        ),
    )
    # A FLASH notification auto-dismisses after `flash_time` (5s), so the
    # screen is inherently non-stable here — `stability()` cannot be used
    # (it races the dismissal). Use fixed sleeps: give the sticky→flash
    # transition time to settle, but capture well within the 5s window.
    await asyncio.sleep(2.5)
    snap('07-flash')

    # Wait past `flash_time` so `_auto_dismiss` fires: the FLASH is gone
    # and the still-present sticky + background are revealed again.
    await asyncio.sleep(5.0)
    snap('08-after-flash')

    # Tidy up — clear the lingering sticky + background notifications.
    store.dispatch(
        NotificationsClearByIdAction(id=progress_id),
        NotificationsClearByIdAction(id=sticky_id),
    )

    await unload_waiter()


@pytest.mark.timeout(200)
async def test_rapid_notification_home_notification(
    app_context: AppContext,
    window_snapshot: WindowSnapshot,
    store_snapshot: StoreSnapshot[RootState],
    load_services: LoadServices,
    stability: Stability,
    wait_for: WaitFor,
) -> None:
    """A notification→home→notification hop must land on the final view.

    Regression test for the gui-client transition-queue pile-up: clearing
    an on-screen notification (which drops the view to home with an
    *animated* transition) and immediately dispatching another
    notification used to leave the second one stuck in the transition
    queue — the core's ``current_view`` was correct but the screen stayed
    on the home view. With latest-wins transitions the screen must
    converge on the final notification.
    """
    from ubo_app.store.main import store
    from ubo_app.store.services.notifications import (
        Notification,
        NotificationDisplayType,
        NotificationsAddAction,
        NotificationsClearByIdAction,
    )

    unload_waiter = await _boot_minimal_app(app_context, load_services, wait_for)

    def snap(title: str) -> None:
        window_snapshot.take(title=title)
        store_snapshot.take(selector=_normalize_notifications)

    first_id = 'rapid-test:first'
    second_id = 'rapid-test:second'

    # First STICKY notification — owns the screen.
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=first_id,
                title='First Notification',
                content='The first sticky notification.',
                display_type=NotificationDisplayType.STICKY,
                blink=False,
            ),
        ),
    )
    await stability(initial_wait=4)
    snap('01-first')

    # In a single dispatch: clear the on-screen notification (→ home, an
    # animated transition) and add a second one. This is the
    # notification→home→notification hop. The screen must end on the
    # SECOND notification, not stuck on the intermediate home view.
    store.dispatch(
        NotificationsClearByIdAction(id=first_id),
        NotificationsAddAction(
            notification=Notification(
                id=second_id,
                title='Second Notification',
                content='The second sticky notification.',
                display_type=NotificationDisplayType.STICKY,
                blink=False,
            ),
        ),
    )
    await stability(initial_wait=4)
    snap('02-second')

    # Tidy up.
    store.dispatch(NotificationsClearByIdAction(id=second_id))

    await unload_waiter()


@pytest.mark.timeout(200)
async def test_flash_under_background_flood(
    app_context: AppContext,
    window_snapshot: WindowSnapshot,
    store_snapshot: StoreSnapshot[RootState],
    load_services: LoadServices,
    stability: Stability,
    wait_for: WaitFor,
) -> None:
    """A FLASH dispatched after a flood of BACKGROUND updates must render.

    Regression test for the ``subscribe_store`` gRPC queue overflow:
    under a flood of state changes (e.g. a download dispatching a
    BACKGROUND progress notification many times a second), the previous
    FIFO ``Queue(30)`` with drop-newest semantics would either drop the
    FLASH's view-change event or back the gui-client up behind a long
    backlog of status-bar updates — so the FLASH was rendered after its
    ``flash_time`` had nearly elapsed (or not rendered at all). With
    latest-wins coalescing in ``subscribe_store``, the gui-client
    always converges on the most recent state, and the FLASH renders
    promptly even under flood.
    """
    from ubo_app.store.main import store
    from ubo_app.store.services.notifications import (
        Notification,
        NotificationDisplayType,
        NotificationsAddAction,
        NotificationsClearByIdAction,
    )

    unload_waiter = await _boot_minimal_app(app_context, load_services, wait_for)

    def snap(title: str) -> None:
        window_snapshot.take(title=title)
        store_snapshot.take(selector=_normalize_notifications)

    sticky_id = 'flood-test:sticky'
    progress_id = 'flood-test:progress'
    flash_id = 'flood-test:flash'

    # Sticky first — owns the screen, baseline before the flood.
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=sticky_id,
                title='Sticky',
                content='Sticky owns the screen.',
                display_type=NotificationDisplayType.STICKY,
                blink=False,
            ),
        ),
    )
    await stability(initial_wait=4)
    snap('01-sticky')

    # Flood ~100 BACKGROUND progress updates as fast as possible. Each
    # one updates ``state.notifications.progress`` → fires the core's
    # view autorun → dispatches ``UpdateCurrentViewAction`` →
    # ``ViewChangedEvent`` → ``subscribe_store`` pushes a new
    # ``partial_state`` for the gui-client. Under the old FIFO Queue(30)
    # behaviour this saturates the queue and the FLASH's later state
    # change gets dropped or backlogged.
    flood_count = 100
    for i in range(flood_count):
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id=progress_id,
                    title='Flooding',
                    content=f'progress step {i + 1}/{flood_count}',
                    display_type=NotificationDisplayType.BACKGROUND,
                    progress=(i + 1) / flood_count,
                    blink=False,
                ),
            ),
        )
        # Tiny yield so the producer/consumer pattern actually runs;
        # 10 ms cadence ≈ 100 Hz, representative of a fast download.
        await asyncio.sleep(0.01)

    # Dispatch the FLASH immediately after the flood. With latest-wins,
    # the gui-client converges on this latest state quickly; without it,
    # the FLASH event is queued behind dozens of stale status-bar
    # snapshots and arrives late.
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=flash_id,
                title='Flash After Flood',
                content='Visible despite the preceding flood.',
                display_type=NotificationDisplayType.FLASH,
                # 10 s so the snapshot's gRPC capture round-trip on slow
                # hardware can't race the auto-dismiss timer.
                flash_time=10,
                blink=False,
            ),
        ),
    )

    # Poll for screen+store stability instead of a fixed sleep — the
    # gRPC screenshot capture can take longer than any fixed window on
    # slow hardware, and a fixed sleep would race the ``flash_time``
    # auto-dismiss timer.
    await stability(initial_wait=0.5)
    snap('02-flash-after-flood')

    # Wait past ``flash_time`` so ``_auto_dismiss`` fires, then tidy up.
    await asyncio.sleep(9)

    store.dispatch(
        NotificationsClearByIdAction(id=progress_id),
        NotificationsClearByIdAction(id=sticky_id),
    )

    await unload_waiter()
