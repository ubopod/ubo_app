# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from constants import ETHERNET_STATE_ICON_ID, ETHERNET_STATE_ICON_PRIORITY
from debouncer import DebounceOptions, debounce
from ethernet_manager import get_ethernet_device, get_ethernet_device_state

from ubo_app.store.main import store
from ubo_app.store.services.ethernet import NetState
from ubo_app.store.status_icons import StatusIconsRegisterAction
from ubo_app.utils.async_ import create_task


@debounce(
    wait=0.5,
    options=DebounceOptions(leading=True, trailing=True, time_window=1),
)
async def update_ethernet_icon() -> None:
    state = await get_ethernet_device_state()
    store.dispatch(
        StatusIconsRegisterAction(
            icon={
                NetState.CONNECTED: '󱊪',
                NetState.DISCONNECTED: '󰌙',
                NetState.PENDING: '󰌘',
                NetState.NEEDS_ATTENTION: '󰌚',
                NetState.UNKNOWN: '󰈅',
            }[state],
            priority=ETHERNET_STATE_ICON_PRIORITY,
            id=ETHERNET_STATE_ICON_ID,
        ),
    )


async def setup_listeners() -> None:
    ethernet_device = await get_ethernet_device()
    if not ethernet_device:
        return

    async for _ in ethernet_device.properties_changed:
        create_task(update_ethernet_icon())


def init_service() -> None:
    create_task(update_ethernet_icon())
    create_task(setup_listeners())
