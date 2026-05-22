# ruff: noqa: D100
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from agent import resolve_pairing_confirmation
from bluetooth_manager import (
    connect_device,
    disconnect_device,
    pair_device,
    remove_device,
    start_discovery,
    stop_discovery,
)
from constants import (
    BLUETOOTH_CONNECTED_ICON,
    BLUETOOTH_DISCOVERED_MENU_ID,
    BLUETOOTH_ICON,
    BLUETOOTH_PAIRED_MENU_ID,
    BLUETOOTH_SETTINGS_MENU_ID,
    DISCOVERY_POLL_INTERVAL,
    get_device_icon,
)

from ubo_app.store.core.action_registry import register_action
from ubo_app.store.core.types import (
    MenuItemData,
    PromptStackItem,
    StackPopAction,
    StackPushPromptAction,
    UpdateDynamicMenuAction,
    UpdatePromptAction,
)
from ubo_app.store.main import store
from ubo_app.store.services.bluetooth import (
    BluetoothDevice,
    BluetoothUpdateRequestAction,
)
from ubo_app.utils import IS_RPI
from ubo_app.utils.async_ import create_task

if TYPE_CHECKING:
    from collections.abc import Coroutine, Sequence

# Action-id prefixes for per-device menu actions.
_PAIR_PREFIX = 'bluetooth:pair:'
_OPEN_PREFIX = 'bluetooth:open-device:'
_CONNECT_PREFIX = 'bluetooth:connect:'
_DISCONNECT_PREFIX = 'bluetooth:disconnect:'
_REMOVE_PREFIX = 'bluetooth:remove:'

# The running discovery-poll task, tracked so `_discovery_lifecycle` can cancel
# it when the user leaves the discovered-devices menu. A module-level container
# (not a global) per the project's no-globals rule.
_discovery_task: list[asyncio.Task[Any] | None] = [None]


# --- "Bluetooth Settings" menu (Add / Select) -------------------------------

store.dispatch(
    UpdateDynamicMenuAction(
        menu_id=BLUETOOTH_SETTINGS_MENU_ID,
        title='Bluetooth',
        items=(
            MenuItemData(
                key='bluetooth:discovered',
                label='Add',
                icon='󱛃',
                action_id='bluetooth:scan',
            ),
            MenuItemData(
                key='bluetooth:paired',
                label='Select',
                icon='󱖫',
                action_id='bluetooth:select-paired',
            ),
        ),
    ),
)


# --- Helpers ----------------------------------------------------------------


async def _refresh_after(coroutine: Coroutine[None, None, None]) -> None:
    """Run a device operation, then request a device-list refresh."""
    await coroutine
    store.dispatch(BluetoothUpdateRequestAction())


def _paired_device_icon(device: BluetoothDevice) -> str:
    """Icon for a paired device, highlighting the connected one."""
    if device.connected:
        return BLUETOOTH_CONNECTED_ICON
    return get_device_icon(device.icon)


def _is_named(device: BluetoothDevice) -> bool:
    """Whether the device advertises a human-readable name.

    Many nearby devices never advertise a name; for those, BlueZ reports the
    MAC address itself as the name (dash-formatted). Comparing the name to the
    address — ignoring separators and case — detects that fallback so genuinely
    named devices can be sorted above the anonymous MAC-only ones.
    """
    normalized_name = device.name.replace('-', '').replace(':', '').upper()
    normalized_address = device.address.replace(':', '').upper()
    return normalized_name != normalized_address


def _build_device_prompt_items(
    device: BluetoothDevice,
) -> tuple[MenuItemData, ...]:
    """Connect/Disconnect + Remove items for a paired-device prompt."""
    if device.connected:
        first = MenuItemData(
            key='connect-disconnect',
            label='Disconnect',
            icon='󰂲',
            action_id=f'{_DISCONNECT_PREFIX}{device.address}',
        )
    else:
        first = MenuItemData(
            key='connect-disconnect',
            label='Connect',
            icon='󰂱',
            action_id=f'{_CONNECT_PREFIX}{device.address}',
        )
    return (
        first,
        MenuItemData(
            key='remove',
            label='Remove',
            icon='󰆴',
            action_id=f'{_REMOVE_PREFIX}{device.address}',
        ),
    )


def _address_from_prompt_items(items: tuple[MenuItemData, ...]) -> str | None:
    """Extract the device address encoded in a prompt's action ids."""
    for item in items:
        for prefix in (_CONNECT_PREFIX, _DISCONNECT_PREFIX, _REMOVE_PREFIX):
            if item.action_id and item.action_id.startswith(prefix):
                return item.action_id[len(prefix) :]
    return None


# --- Settings action handlers -----------------------------------------------


def _on_scan() -> bool:
    """Navigate into the discovered-devices menu.

    Scanning and the periodic device-list polling are driven entirely by
    ``_discovery_lifecycle`` for as long as that menu stays open, so there is
    nothing to start here.
    """
    return True


def _on_select_paired() -> bool:
    """Refresh and navigate into the paired-devices menu."""
    store.dispatch(BluetoothUpdateRequestAction())
    return True


register_action('bluetooth:scan', _on_scan)
register_action('bluetooth:select-paired', _on_select_paired)


# --- Per-device action handlers (prefix handlers) ---------------------------


def _on_pair(action_id: str) -> None:
    address = action_id[len(_PAIR_PREFIX) :]
    create_task(_refresh_after(pair_device(address)))


def _on_connect(action_id: str) -> None:
    address = action_id[len(_CONNECT_PREFIX) :]
    create_task(_refresh_after(connect_device(address)))


def _on_disconnect(action_id: str) -> None:
    address = action_id[len(_DISCONNECT_PREFIX) :]
    create_task(_refresh_after(disconnect_device(address)))


def _on_remove(action_id: str) -> None:
    address = action_id[len(_REMOVE_PREFIX) :]
    store.dispatch(StackPopAction())
    create_task(_refresh_after(remove_device(address)))


def _on_open_device(action_id: str) -> None:
    address = action_id[len(_OPEN_PREFIX) :]

    @store.with_state(lambda state: state.bluetooth.devices)
    def _push(devices: Sequence[BluetoothDevice] | None) -> None:
        device = next(
            (item for item in devices or [] if item.address == address),
            None,
        )
        if device is None:
            return
        store.dispatch(
            StackPushPromptAction(
                prompt=device.name,
                icon=(
                    BLUETOOTH_CONNECTED_ICON
                    if device.connected
                    else BLUETOOTH_ICON
                ),
                items=_build_device_prompt_items(device),
            ),
        )

    _push()


register_action(f'{_PAIR_PREFIX}*', _on_pair)
register_action(f'{_OPEN_PREFIX}*', _on_open_device)
register_action(f'{_CONNECT_PREFIX}*', _on_connect)
register_action(f'{_DISCONNECT_PREFIX}*', _on_disconnect)
register_action(f'{_REMOVE_PREFIX}*', _on_remove)


# --- Pairing confirmation handlers ------------------------------------------


def _on_pairing_confirm() -> None:
    resolve_pairing_confirmation(accepted=True)


def _on_pairing_reject() -> None:
    resolve_pairing_confirmation(accepted=False)


register_action('bluetooth:pairing-confirm', _on_pairing_confirm)
register_action('bluetooth:pairing-reject', _on_pairing_reject)


# --- Dynamic device menus ---------------------------------------------------


@store.autorun(
    lambda state: (state.bluetooth.devices, state.bluetooth.is_scanning),
)
def update_device_menus(
    data: tuple[Sequence[BluetoothDevice] | None, bool],
) -> None:
    """Render the discovered- and paired-device dynamic menus."""
    devices, is_scanning = data

    if not IS_RPI:
        placeholder = 'D-Bus unavailable on this platform'
        discovered_items: tuple[MenuItemData | None, ...] = ()
        paired_items: tuple[MenuItemData | None, ...] = ()
        discovered_placeholder = placeholder
        paired_placeholder = placeholder
    elif devices is None:
        discovered_items = ()
        paired_items = ()
        discovered_placeholder = 'Loading...'
        paired_placeholder = 'Loading...'
    else:
        # Named devices first (alphabetically), then anonymous MAC-only ones,
        # so the user's device is easy to find in a crowded list.
        sorted_discovered = sorted(
            (device for device in devices if not device.paired),
            key=lambda device: (not _is_named(device), device.name.lower()),
        )
        discovered_items = tuple(
            MenuItemData(
                key=f'device:{device.address}',
                label=device.name,
                icon=get_device_icon(device.icon),
                action_id=f'{_PAIR_PREFIX}{device.address}',
            )
            for device in sorted_discovered
        )
        paired_items = tuple(
            MenuItemData(
                key=f'device:{device.address}',
                label=device.name,
                icon=_paired_device_icon(device),
                action_id=f'{_OPEN_PREFIX}{device.address}',
            )
            for device in devices
            if device.paired
        )
        discovered_placeholder = 'Scanning…' if is_scanning else 'No devices found'
        paired_placeholder = 'No paired devices'

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=BLUETOOTH_DISCOVERED_MENU_ID,
            title='Add Device',
            items=discovered_items,
            placeholder=discovered_placeholder,
        ),
        UpdateDynamicMenuAction(
            menu_id=BLUETOOTH_PAIRED_MENU_ID,
            title='Paired Devices',
            items=paired_items,
            placeholder=paired_placeholder,
        ),
    )


# --- Reactive updates -------------------------------------------------------


@store.autorun(lambda state: state.bluetooth.devices)
def _update_device_prompt(devices: Sequence[BluetoothDevice] | None) -> None:
    """Keep an open paired-device prompt in sync with device state."""
    if devices is None:
        return

    devices_by_address = {device.address: device for device in devices}

    @store.with_state(lambda state: state.main.stack)
    def _check_stack(stack: tuple[object, ...]) -> None:
        top = stack[-1] if stack else None
        if not isinstance(top, PromptStackItem):
            return
        address = _address_from_prompt_items(top.items)
        if address is None:
            return
        device = devices_by_address.get(address)
        if device is None:
            return
        store.dispatch(
            UpdatePromptAction(
                icon=(
                    BLUETOOTH_CONNECTED_ICON
                    if device.connected
                    else BLUETOOTH_ICON
                ),
                items=_build_device_prompt_items(device),
            ),
        )

    _check_stack()


async def _poll_discovered_devices() -> None:
    """Scan and refresh the discovered-device list every poll interval.

    Started when the user opens the discovered-devices menu and cancelled by
    ``_discovery_lifecycle`` when they leave it. The ``finally`` block stops
    BlueZ discovery whether the loop exits normally or via cancellation, so no
    scanning continues once the menu is closed.
    """
    try:
        await start_discovery()
        while True:
            store.dispatch(BluetoothUpdateRequestAction())
            await asyncio.sleep(DISCOVERY_POLL_INTERVAL)
    finally:
        await stop_discovery()


def _remember_discovery_task(task: asyncio.Task[Any]) -> None:
    """Track the running poll task so the lifecycle autorun can cancel it."""
    _discovery_task[0] = task


@store.autorun(lambda state: 'bluetooth:discovered' in state.main.path)
def _discovery_lifecycle(is_discovered_menu_open: bool) -> None:  # noqa: FBT001
    """Scan and poll only while the discovered-devices menu is open.

    Opening the menu starts a single polling task; leaving it cancels that
    task, which stops BlueZ discovery in its ``finally`` block. No scanning or
    polling happens while the menu is closed.
    """
    task = _discovery_task[0]
    if is_discovered_menu_open:
        if task is None or task.done():
            create_task(
                _poll_discovered_devices(),
                callback=_remember_discovery_task,
            )
    elif task is not None and not task.done():
        task.cancel()
