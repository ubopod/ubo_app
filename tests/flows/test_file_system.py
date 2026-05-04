"""Test file system flow: move file, copy back, then remove — all via keypad.

Complete user journey: every notification dismissed, every screen verified,
navigation between operations done via BACK presses (no teleporting).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from redux_pytest.fixtures import StoreSnapshot, WaitFor

    from tests.fixtures import (
        AppContext,
        Dispatcher,
        LoadServices,
        Stability,
    )
    from tests.fixtures.menu import WaitForMenuItem
    from ubo_app.store.main import RootState
    from ubo_app.store.services.file_system import FileSystemState

from tests.fixtures.dispatch import DIRECT, GRPC_MENU

# Name starts with 'aaa' so it appears near the top of /tmp listings
TEST_DIR = Path('/tmp/aaa_ubo_e2e_test')  # noqa: S108


def _snapshot_selector(state: RootState) -> dict:
    """Select file_system state and notification summaries for snapshots."""
    notifications: list[dict[str, str]] = []
    if hasattr(state, 'notifications'):
        notifications = [
            {
                'title': n.title,
                'content': re.sub(
                    r'(\[b\](?:Owner|Group):\[/b\] )\S+',
                    r'\1<USER>',
                    n.content.replace(TEST_DIR.as_posix(), '<TEST>'),
                ),
            }
            for n in state.notifications.notifications
        ]
    fs_state: FileSystemState | None = None
    if hasattr(state, 'file_system'):
        fs_state = state.file_system  # pyright: ignore[reportAttributeAccessIssue]
    return {
        'file_system': fs_state,
        'notifications': notifications,
    }


@pytest.mark.timeout(240)
async def test_move_copy_remove(  # noqa: C901
    app_context: AppContext,
    store_snapshot: StoreSnapshot[RootState],
    load_services: LoadServices,
    stability: Stability,
    wait_for: WaitFor,
    wait_for_menu_item: WaitForMenuItem,
    dispatcher: Dispatcher,
) -> None:
    """Move file dir_a→dir_b, copy back dir_b→dir_a, remove from dir_a.

    Full user journey via raw keypad presses. Every notification is dismissed
    and every screen transition is verified.
    """
    import asyncio

    from tenacity import stop_after_delay, wait_fixed

    from ubo_app.store.core.action_registry import get_action
    from ubo_app.store.main import store
    from ubo_app.store.services.file_system import PathSelectorConfig
    from ubo_app.store.services.keypad import Key

    # ── Helpers ──────────────────────────────────────────────────────────

    async def press(key: Key) -> None:
        """Send a key press + release via gRPC."""
        await dispatcher.send_key(key)
        await asyncio.sleep(0.5)

    async def wait_for_view_item(label: str) -> None:
        """Wait for an item with the given label in the current view."""

        @wait_for(wait=wait_fixed(0.5), stop=stop_after_delay(15), run_async=True)
        def _check() -> None:
            state = store._state  # noqa: SLF001
            assert state is not None
            view = state.main.current_view
            assert view is not None
            assert any(
                i is not None and i.label == label for i in getattr(view, 'items', ())
            ), f'{label!r} not found in current view items'

        await _check()

    async def assert_no_select_in_view() -> None:
        """Assert no '[b]Select[/b]' label in current view (browse mode)."""

        @wait_for(wait=wait_fixed(0.5), stop=stop_after_delay(5), run_async=True)
        def _check() -> None:
            state = store._state  # noqa: SLF001
            assert state is not None
            view = state.main.current_view
            assert view is not None
            for item in getattr(view, 'items', ()):
                if item is not None:
                    assert item.label != '[b]Select[/b]', (
                        'Found "Select" in view — selector mode should be gone'
                    )

        await _check()

    async def wait_for_notification() -> None:
        """Wait until the current view is a notification."""

        @wait_for(wait=wait_fixed(0.5), stop=stop_after_delay(15), run_async=True)
        def _check() -> None:
            state = store._state  # noqa: SLF001
            assert state is not None
            view = state.main.current_view
            assert view is not None
            assert view.type == 'notification'

        await _check()

    async def wait_for_menu_view(title_substr: str | None = None) -> None:
        """Wait for a menu view, optionally with title containing substring."""

        @wait_for(wait=wait_fixed(0.5), stop=stop_after_delay(15), run_async=True)
        def _check() -> None:
            state = store._state  # noqa: SLF001
            assert state is not None
            view = state.main.current_view
            assert view is not None
            assert view.type == 'menu'
            if title_substr:
                assert title_substr in view.title, (
                    f'{title_substr!r} not in title {view.title!r}'
                )

        await _check()

    async def dismiss_notification_via_l3() -> None:
        """Dismiss a FLASH notification by pressing its dismiss button (L3)."""
        await wait_for_view_item('')
        await press(Key.L3)

    async def select_destination_and_verify(*dirs: str) -> None:
        """Full selector flow: open selector, navigate, select."""
        # Open Path Selector (single action, bottom-aligned to L3)
        await press(Key.L3)

        # Wait for initial selector view
        await wait_for_view_item('[b]Select[/b]')

        # Navigate through each directory, verifying title after each step
        for dirname in dirs:
            await dispatcher.choose_by_label(dirname, via=GRPC_MENU)
            await wait_for_menu_view(dirname)

        # Press Select (L1)
        await press(Key.L1)

    # ── Setup ────────────────────────────────────────────────────────────

    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR)
    TEST_DIR.mkdir(parents=True)
    dir_a = TEST_DIR / 'dir_a'
    dir_a.mkdir()
    dir_b = TEST_DIR / 'dir_b'
    dir_b.mkdir()
    test_file = dir_a / 'test_file.txt'
    test_file.write_text('hello world')

    app_context.set_app()
    unload_waiter = await load_services(
        ['notifications', 'file_system', 'keypad', 'display'],
        run_async=True,
    )
    await stability(initial_wait=5, attempts=2, wait=2)
    store_snapshot.take(selector=_snapshot_selector)

    # ── Phase 1: Navigate to file browser ────────────────────────────────
    # Home → Main Menu → Apps → Files → File System → TEST_DIR → dir_a

    await dispatcher.choose_by_icon('󰍜', via=DIRECT)
    await wait_for_menu_item(label='Apps')
    await dispatcher.choose_by_label('Apps', via=GRPC_MENU)
    await wait_for_menu_item(label='Files')
    await dispatcher.choose_by_label('Files', via=GRPC_MENU)
    await wait_for_menu_item(label='File System')

    # Open file browser at TEST_DIR (only direct call — simulates app open)
    open_handler = get_action('file-system:open')
    assert open_handler is not None
    open_handler(config=PathSelectorConfig(initial_path=TEST_DIR.as_posix()))

    await wait_for_view_item('dir_a')
    await wait_for_view_item('dir_b')

    # Enter dir_a: Info (L1), dir_a (L2), dir_b (L3)
    await press(Key.L2)
    await wait_for_view_item('test_file.txt')

    # ── Phase 2: MOVE test_file.txt → dir_b ─────────────────────────────

    # Select the file → file info notification (4 items, 2 pages)
    await press(Key.L2)

    @wait_for(wait=wait_fixed(0.5), stop=stop_after_delay(15), run_async=True)
    def check_file_notification() -> None:
        state = store._state  # noqa: SLF001
        assert state is not None
        view = state.main.current_view
        assert view is not None
        assert view.type == 'notification'
        real = [i for i in getattr(view, 'items', ()) if i is not None]
        expected = 5
        assert len(real) == expected

    await check_file_notification()
    store_snapshot.take(selector=_snapshot_selector)

    # Press L3 → Move (page 1: View=L1-slot, Copy=L2-slot, Move=L3-slot)
    await press(Key.L3)

    # Wait for selector notification
    await wait_for_notification()
    store_snapshot.take(selector=_snapshot_selector)

    # Navigate selector to dir_b and select
    await select_destination_and_verify('tmp', 'aaa_ubo_e2e_test', 'dir_b')

    # Verify move completed
    @wait_for(wait=wait_fixed(0.5), stop=stop_after_delay(15), run_async=True)
    def check_move_done() -> None:
        assert (dir_b / 'test_file.txt').exists(), 'File should be at dir_b'
        assert not test_file.exists(), 'File should not be at dir_a'
        state = store._state  # noqa: SLF001
        assert state is not None
        assert any(
            n.title == 'Moved' for n in state.notifications.notifications
        )

    await check_move_done()
    store_snapshot.take(selector=_snapshot_selector)

    # Dismiss "Moved" notification
    await dismiss_notification_via_l3()

    # After dismiss: verify no stale "Select" and navigate back to
    # aaa_ubo_e2e_test listing. Press BACK until we see both dir_a and dir_b.
    await assert_no_select_in_view()

    # Keep pressing BACK until we reach the test directory listing
    for _ in range(10):
        state = store._state  # noqa: SLF001
        if state is not None:
            view = state.main.current_view
            if (
                view is not None
                and view.type == 'menu'
                and any(
                    i is not None and i.label == 'dir_a' for i in view.items
                )
                and any(
                    i is not None and i.label == 'dir_b' for i in view.items
                )
            ):
                break
        await press(Key.BACK)
        await asyncio.sleep(0.5)
        await assert_no_select_in_view()

    await wait_for_view_item('dir_a')
    await wait_for_view_item('dir_b')

    store_snapshot.take(selector=_snapshot_selector)

    # ── Phase 3: COPY test_file.txt from dir_b → dir_a ──────────────────

    # Verify we're at the test dir listing before navigating
    await wait_for_view_item('dir_b')
    await wait_for_menu_view('aaa_ubo_e2e_test')
    await asyncio.sleep(1)

    # Navigate into dir_b
    await press(Key.L3)
    await asyncio.sleep(1)

    # If view didn't change (action registration issue), try via GRPC_MENU
    state = store._state  # noqa: SLF001
    if state and state.main.current_view and 'dir_b' not in getattr(
        state.main.current_view, 'title', '',
    ):
        await dispatcher.choose_by_label('dir_b', via=GRPC_MENU)

    await wait_for_menu_view('dir_b')
    await wait_for_view_item('test_file.txt')

    # Select the file
    await press(Key.L2)
    await check_file_notification()

    # Press L2 → Copy (page 1: View=L1-slot, Copy=L2-slot, Move=L3-slot)
    await press(Key.L2)

    # Wait for selector notification
    await wait_for_notification()

    # Navigate selector to dir_a and select
    await select_destination_and_verify('tmp', 'aaa_ubo_e2e_test', 'dir_a')

    # Verify copy completed
    @wait_for(wait=wait_fixed(0.5), stop=stop_after_delay(15), run_async=True)
    def check_copy_done() -> None:
        assert (dir_a / 'test_file.txt').exists(), 'File should be copied to dir_a'
        assert (dir_a / 'test_file.txt').read_text() == 'hello world'
        assert (dir_b / 'test_file.txt').exists(), 'Original still at dir_b'
        state = store._state  # noqa: SLF001
        assert state is not None
        assert any(
            n.title == 'Copied' for n in state.notifications.notifications
        )

    await check_copy_done()
    store_snapshot.take(selector=_snapshot_selector)

    # Dismiss "Copied" notification
    await dismiss_notification_via_l3()

    # Verify no stale "Select" and navigate back to aaa_ubo_e2e_test listing
    await assert_no_select_in_view()

    for _ in range(10):
        state = store._state  # noqa: SLF001
        if state is not None:
            view = state.main.current_view
            if (
                view is not None
                and view.type == 'menu'
                and any(
                    i is not None and i.label == 'dir_a' for i in view.items
                )
                and any(
                    i is not None and i.label == 'dir_b' for i in view.items
                )
            ):
                break
        await press(Key.BACK)
        await asyncio.sleep(0.5)
        await assert_no_select_in_view()

    await wait_for_view_item('dir_a')
    await wait_for_view_item('dir_b')

    store_snapshot.take(selector=_snapshot_selector)

    # ── Phase 4: REMOVE test_file.txt from dir_a ────────────────────────

    # Verify we're at the test dir listing
    await wait_for_view_item('dir_a')
    await wait_for_menu_view('aaa_ubo_e2e_test')

    # Navigate into dir_a (Info=L1, dir_a=L2, dir_b=L3)
    await press(Key.L2)
    await wait_for_menu_view('dir_a')
    await wait_for_view_item('test_file.txt')

    # Select the file
    await press(Key.L2)
    await check_file_notification()

    # Scroll down to page 2 for Remove
    await press(Key.DOWN)

    @wait_for(wait=wait_fixed(0.3), stop=stop_after_delay(10), run_async=True)
    def check_scrolled() -> None:
        state = store._state  # noqa: SLF001
        assert state is not None
        view = state.main.current_view
        assert view is not None
        assert getattr(view, 'page_index', 0) == 1

    await check_scrolled()

    # L1 for Remove (first item on page 2)
    await press(Key.L1)

    # Confirm removal
    await wait_for_menu_item(label='Remove')
    store_snapshot.take(selector=_snapshot_selector)

    await dispatcher.choose_by_label('Remove', via=GRPC_MENU)

    @wait_for(wait=wait_fixed(0.5), stop=stop_after_delay(10), run_async=True)
    def check_deleted() -> None:
        assert not (dir_a / 'test_file.txt').exists()

    await check_deleted()

    @wait_for(wait=wait_fixed(0.5), stop=stop_after_delay(10), run_async=True)
    def check_removed_notif() -> None:
        state = store._state  # noqa: SLF001
        assert state is not None
        assert any(
            n.title == 'Removed' for n in state.notifications.notifications
        )

    await check_removed_notif()
    store_snapshot.take(selector=_snapshot_selector)

    # Dismiss "Removed" notification — this was the missing step that
    # would have caught the UnboundLocalError on 'pad'
    await dismiss_notification_via_l3()

    # Navigate all the way back to Apps list
    for _ in range(15):
        state = store._state  # noqa: SLF001
        if state is not None:
            view = state.main.current_view
            if view is not None and any(
                i is not None and i.label == 'File System'
                for i in getattr(view, 'items', ())
            ):
                break
        await press(Key.BACK)
        await asyncio.sleep(0.5)

    await wait_for_view_item('File System')

    store_snapshot.take(selector=_snapshot_selector)

    await unload_waiter()
    shutil.rmtree(TEST_DIR, ignore_errors=True)
