# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from pathlib import Path

from constants import ETHERNET_STATE_ICON_ID, ETHERNET_STATE_ICON_PRIORITY
from debouncer import DebounceOptions, debounce
from ethernet_manager import get_ethernet_device, get_ethernet_device_state

from ubo_app.store import dispatch
from ubo_app.store.ethernet import GlobalEthernetState
from ubo_app.store.status_icons import StatusIconsRegisterAction
from ubo_app.utils.async_ import create_task

IS_RPI = Path('/etc/rpi-issue').exists()


@debounce(
    wait=0.5,
    options=DebounceOptions(leading=True, trailing=False, time_window=2),
)
async def update_ethernet_icon() -> None:
    state = await get_ethernet_device_state()
    dispatch(
        StatusIconsRegisterAction(
            icon={
                GlobalEthernetState.CONNECTED: 'link',
                GlobalEthernetState.DISCONNECTED: 'link_off',
                GlobalEthernetState.PENDING: 'settings_ethernet',
                GlobalEthernetState.NEEDS_ATTENTION: ('settings_ethernet'),
                GlobalEthernetState.UNKNOWN: 'indeterminate_question_box',
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
