# ruff: noqa: D100, D103
from __future__ import annotations

from typing import TYPE_CHECKING

from agent import register_agent, unregister_agent
from bluetooth_manager import (
    get_adapter_state,
    get_devices,
    get_object_manager,
    stop_discovery,
)
from constants import (
    BLUETOOTH_DISCOVERED_MENU_ID,
    BLUETOOTH_ICON,
    BLUETOOTH_PAIRED_MENU_ID,
    BLUETOOTH_SETTINGS_MENU_ID,
)
from debouncer import DebounceOptions, debounce

from ubo_app.store.core.types import RegisterSettingAppAction, SettingsCategory
from ubo_app.store.core.view_registry import (
    create_settings_path_matcher,
    register_path_menu_matcher,
)
from ubo_app.store.main import store
from ubo_app.store.services.bluetooth import (
    BluetoothUpdateAction,
    BluetoothUpdateRequestEvent,
)
from ubo_app.utils import IS_RPI
from ubo_app.utils.async_ import create_task

if TYPE_CHECKING:
    from ubo_app.utils.types import Subscriptions

# Sub-menus live two levels below the settings category, so their navigation
# path always has at least this many elements.
MIN_SUBMENU_PATH_LENGTH = 5


@debounce(
    wait=0.5,
    options=DebounceOptions(leading=True, trailing=True, time_window=2),
)
async def update_devices(_: BluetoothUpdateRequestEvent | None = None) -> None:
    is_powered, is_scanning = await get_adapter_state()
    store.dispatch(
        BluetoothUpdateAction(
            devices=await get_devices(),
            is_powered=is_powered,
            is_scanning=is_scanning,
        ),
    )


async def setup_listeners() -> None:
    """Refresh the device list whenever BlueZ reports an object change."""
    if not IS_RPI:
        return

    object_manager = get_object_manager()

    async def _on_interfaces_added() -> None:
        async for _ in object_manager.interfaces_added:
            create_task(update_devices())

    async def _on_interfaces_removed() -> None:
        async for _ in object_manager.interfaces_removed:
            create_task(update_devices())

    create_task(_on_interfaces_added())
    create_task(_on_interfaces_removed())


def init_service() -> Subscriptions:
    create_task(update_devices())
    create_task(setup_listeners())
    create_task(register_agent())

    store.dispatch(
        RegisterSettingAppAction(
            priority=1,
            category=SettingsCategory.NETWORK,
            label='Bluetooth',
            icon=BLUETOOTH_ICON,
        ),
    )

    register_path_menu_matcher(
        'bluetooth:settings',
        create_settings_path_matcher('bluetooth:', BLUETOOTH_SETTINGS_MENU_ID),
    )

    register_path_menu_matcher(
        'bluetooth:discovered',
        lambda path: BLUETOOTH_DISCOVERED_MENU_ID
        if len(path) >= MIN_SUBMENU_PATH_LENGTH
        and path[3] == 'bluetooth:'
        and path[4] == 'bluetooth:discovered'
        else None,
        priority=1,
    )

    register_path_menu_matcher(
        'bluetooth:paired',
        lambda path: BLUETOOTH_PAIRED_MENU_ID
        if len(path) >= MIN_SUBMENU_PATH_LENGTH
        and path[3] == 'bluetooth:'
        and path[4] == 'bluetooth:paired'
        else None,
        priority=1,
    )

    # Import pages/main to set up dynamic menus and action handlers.
    from pages import main as _pages_main  # noqa: F401

    async def _cleanup() -> None:
        await stop_discovery()
        await unregister_agent()

    return [
        store.subscribe_event(BluetoothUpdateRequestEvent, update_devices),
        _cleanup,
    ]
