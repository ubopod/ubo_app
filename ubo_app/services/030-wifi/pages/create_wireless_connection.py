# ruff: noqa: D100
from __future__ import annotations

import asyncio
import functools
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from constants import WIFI_SCAN_MENU_ID, get_signal_icon
from wifi_manager import WiFiNetwork, add_wireless_connection, get_available_networks

from pages.wifi_input_descriptions import (
    OTHER_OPTION,
    full_webui_description,
    network_select_description,
    parse_full_result,
    password_only_description,
    qr_description,
)
from ubo_app.colors import SUCCESS_COLOR, WARNING_COLOR
from ubo_app.logger import logger
from ubo_app.store.core.action_registry import register_action, unregister_action
from ubo_app.store.core.callback_registry import register_auto_callback
from ubo_app.store.core.types import (
    MenuItemData,
    OpenRenderAction,
    StackPopAction,
    StackPushMenuAction,
    UpdateDynamicMenuAction,
)
from ubo_app.store.input.types import InputMethod
from ubo_app.store.main import store
from ubo_app.store.services.notification_helpers import create_notification_action
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
    NotificationsClearByIdAction,
)
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.store.services.wifi import (
    WiFiStopHotspotAction,
    WiFiType,
    WiFiUpdateRequestAction,
)
from ubo_app.utils import IS_UBO_POD
from ubo_app.utils.async_ import create_task
from ubo_app.utils.input import ubo_input
from ubo_app.utils.network import has_gateway

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

HOTSPOT_GRACE_TIME = 5

# On-device scan-results menu (pod offline flow). A single prefix handler keyed
# on an opaque network id avoids leaking a per-SSID handler on every scan.
_SCAN_ACTION_PREFIX = 'wifi:scan-select:'
_OTHER_ID = 'other'


@dataclass
class _ScanContext:
    """Current scan-menu selection context for the single prefix handler."""

    networks: dict[str, WiFiNetwork] = field(default_factory=dict)
    on_creating: Callable[[], None] | None = None


_scan_context = _ScanContext()


# --- Connection finalization ---


async def _finalize_connection(  # noqa: PLR0913
    ssid: str,
    password: str | None,
    type: WiFiType | None,
    *,
    hidden: bool,
    started_hotspot: bool,
    method: InputMethod | None = None,
    on_creating: Callable[[], None] | None = None,
) -> None:
    type = type or WiFiType.NOPASS
    if not password and type != WiFiType.NOPASS:
        logger.warning('Password is required')
        if started_hotspot:
            store.dispatch(WiFiStopHotspotAction())
        return

    if on_creating:
        on_creating()

    if started_hotspot:
        # The Wi-Fi journey is complete: explicitly tear down the hotspot so we
        # can join the target network (a single radio can't host the AP and act
        # as a station at once).
        store.dispatch(WiFiStopHotspotAction())

    if method is InputMethod.WEB_DASHBOARD:
        logger.debug(
            'wifi connection input - waiting for hotspot to go down',
            extra={'grace time': HOTSPOT_GRACE_TIME},
        )
        notification = Notification(
            id='wifi-wait-hotspot',
            title='Please wait!',
            content='To avoid interference we need to wait for the hotspot to go down.',
            display_type=NotificationDisplayType.STICKY,
            color=WARNING_COLOR,
            icon='󱋆',
        )
        store.dispatch(NotificationsAddAction(notification=notification))
        await asyncio.sleep(HOTSPOT_GRACE_TIME)
        store.dispatch(NotificationsClearByIdAction(id='wifi-wait-hotspot'))

    logger.debug('wifi connection input - creating connection')
    try:
        await add_wireless_connection(
            ssid=ssid,
            password=password or '',
            type=type,
            hidden=hidden,
        )
    except Exception:
        logger.exception('wifi connection input - error while creating connection')
        raise

    logger.info(
        'Wireless connection created',
        extra={
            'ssid': ssid,
            'password': '<HIDDEN>' if password else '<NOT PROVIDED>',
            'type': type,
            'hidden': hidden,
        },
    )

    store.dispatch(
        WiFiUpdateRequestAction(reset=True),
        NotificationsAddAction(
            notification=Notification(
                title=f'"{ssid}" Added',
                content=f'WiFi connection with ssid "{ssid}" was added successfully',
                display_type=NotificationDisplayType.FLASH,
                color=SUCCESS_COLOR,
                icon='󱛃',
                chime=Chime.ADD,
            ),
        ),
    )


# --- Web form steps (shared by pod & headless once a network is chosen) ---


async def _connect_with_password_form(
    network: WiFiNetwork,
    on_creating: Callable[[], None] | None,
) -> None:
    """Bring up the hotspot, ask only for the password, then connect."""
    try:
        _, result = await ubo_input(
            prompt=f'Enter password for "{network.ssid}"',
            descriptions=[password_only_description()],
        )
    except asyncio.CancelledError:
        store.dispatch(WiFiStopHotspotAction())
        return
    except Exception:
        store.dispatch(WiFiStopHotspotAction())
        logger.exception('wifi connection input - error')
        raise

    password = (result.data.get('Password') if result else None) or ''
    await _finalize_connection(
        network.ssid,
        password,
        network.type,
        hidden=False,
        started_hotspot=True,
        method=result.method if result else None,
        on_creating=on_creating,
    )


async def _connect_with_full_form(
    on_creating: Callable[[], None] | None,
) -> None:
    """Bring up the hotspot and show the full manual form, then connect."""
    try:
        _, result = await ubo_input(
            prompt='Enter WiFi connection',
            descriptions=[full_webui_description()],
        )
    except asyncio.CancelledError:
        store.dispatch(WiFiStopHotspotAction())
        return
    except Exception:
        store.dispatch(WiFiStopHotspotAction())
        logger.exception('wifi connection input - error')
        raise

    if not result:
        store.dispatch(WiFiStopHotspotAction())
        return
    ssid, password, type, hidden = parse_full_result(result)
    if not ssid:
        store.dispatch(WiFiStopHotspotAction())
        return
    await _finalize_connection(
        ssid,
        password,
        type,
        hidden=hidden,
        started_hotspot=True,
        method=result.method,
        on_creating=on_creating,
    )


# --- Pod offline flow: on-device scan list ---


def register_scan_action_handler() -> Callable[[], None]:
    """Register the single scan-menu selection handler; returns an unregister."""
    action_id = f'{_SCAN_ACTION_PREFIX}*'
    register_action(action_id, _on_scan_pick, allow_reregister=True)

    def unregister() -> None:
        unregister_action(action_id)

    return unregister


def _present_scan_menu(
    networks: Sequence[WiFiNetwork],
    on_creating: Callable[[], None] | None,
    *,
    replace_top: bool = False,
) -> None:
    _scan_context.networks = {
        str(index): network for index, network in enumerate(networks)
    }
    _scan_context.on_creating = on_creating

    items: list[MenuItemData | None] = [
        MenuItemData(
            key='other',
            label='Other…',
            icon='󰏵',
            action_id=f'{_SCAN_ACTION_PREFIX}{_OTHER_ID}',
        ),
    ]
    for network_id, network in _scan_context.networks.items():
        items.append(
            MenuItemData(
                key=f'ssid:{network_id}',
                label=network.ssid,
                icon=get_signal_icon(network.strength),
                action_id=f'{_SCAN_ACTION_PREFIX}{network_id}',
            ),
        )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=WIFI_SCAN_MENU_ID,
            title='Select Network',
            items=tuple(items),
            placeholder='No networks found',
        ),
    )
    if replace_top:
        # Replace the transient "Scanning…" screen with the list in one batch so
        # the screen doesn't flash back to the WiFi menu in between.
        store.dispatch(
            StackPopAction(),
            StackPushMenuAction(menu_key=WIFI_SCAN_MENU_ID),
        )
    else:
        store.dispatch(StackPushMenuAction(menu_key=WIFI_SCAN_MENU_ID))


def _on_scan_pick(action_id: str) -> None:
    # Action handlers must return None; create_task's result is intentionally
    # not returned so no stray submenu frame is pushed.
    network_id = action_id[len(_SCAN_ACTION_PREFIX) :]
    on_creating = _scan_context.on_creating
    network = _scan_context.networks.get(network_id)
    store.dispatch(StackPopAction())
    if network is None:
        # 'Other' (or a stale id): show the full manual form.
        create_task(_connect_with_full_form(on_creating))
    elif network.type is WiFiType.NOPASS:
        # Open network: no password needed, no hotspot needed - connect directly.
        create_task(
            _finalize_connection(
                network.ssid,
                '',
                WiFiType.NOPASS,
                hidden=False,
                started_hotspot=False,
                on_creating=on_creating,
            ),
        )
    else:
        create_task(_connect_with_password_form(network, on_creating))


# --- Offline method chooser (pod: QR vs Hotspot) ---


async def _choose_pod_offline_method(
    input_methods: tuple[InputMethod, ...],
) -> Literal['qr', 'hotspot'] | None:
    allow_qr = not input_methods or InputMethod.CAMERA in input_methods
    allow_hotspot = not input_methods or InputMethod.WEB_DASHBOARD in input_methods
    if not allow_hotspot:
        return 'qr' if allow_qr else None
    if not allow_qr:
        return 'hotspot'

    loop = asyncio.get_running_loop()
    future: asyncio.Future[Literal['qr', 'hotspot']] = loop.create_future()

    def set_result(value: Literal['qr', 'hotspot']) -> None:
        loop.call_soon_threadsafe(future.set_result, value)

    actions = [
        create_notification_action(
            key='camera',
            icon='󰄀',
            label='Camera',
            dismiss_notification=True,
            action=functools.partial(set_result, 'qr'),
        ),
        create_notification_action(
            key='hotspot',
            icon='󰖩',
            label='Hotspot',
            dismiss_notification=True,
            action=functools.partial(set_result, 'hotspot'),
        ),
    ]

    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id='input:method',
                icon='󰌌',
                title='Input method',
                content='Do you want to use the camera or set up a WiFi hotspot?',
                display_type=NotificationDisplayType.STICKY,
                is_read=True,
                extra_information=ReadableInformation(
                    text='You can scan a QR code with the camera, or start a WiFi '
                    'hotspot and pick your network from a list. Please choose one by '
                    'pressing one of the left buttons.',
                ),
                expiration_timestamp=time.time(),
                color='#ffffff',
                show_dismiss_action=False,
                dismiss_on_close=True,
                actions=actions,
                on_close_id=register_auto_callback(
                    lambda: loop.call_soon_threadsafe(future.cancel),
                ),
            ),
        ),
    )

    try:
        return await future
    except asyncio.CancelledError:
        return None


# --- Top-level orchestration ---


async def _route_present_flow(
    input_methods: tuple[InputMethod, ...],
    on_creating: Callable[[], None] | None,
) -> None:
    descriptions = [
        description
        for description in (qr_description(), full_webui_description())
        if not input_methods or description.input_method in input_methods
    ]
    try:
        _, result = await ubo_input(
            prompt='Enter WiFi connection',
            descriptions=descriptions,
        )
    except asyncio.CancelledError:
        logger.debug('wifi connection input - cancelled')
        return
    except Exception:
        logger.exception('wifi connection input - error')
        raise

    if not result:
        return
    ssid, password, type, hidden = parse_full_result(result)
    if not ssid:
        return
    await _finalize_connection(
        ssid,
        password,
        type,
        hidden=hidden,
        started_hotspot=False,
        method=result.method,
        on_creating=on_creating,
    )


async def _pod_offline_flow(
    input_methods: tuple[InputMethod, ...],
    on_creating: Callable[[], None] | None,
) -> None:
    method = await _choose_pod_offline_method(input_methods)
    if method is None:
        return
    if method == 'qr':
        try:
            _, result = await ubo_input(
                prompt='Enter WiFi connection',
                descriptions=[qr_description()],
            )
        except asyncio.CancelledError:
            return
        if not result:
            return
        ssid, password, type, hidden = parse_full_result(result)
        if not ssid:
            return
        await _finalize_connection(
            ssid,
            password,
            type,
            hidden=hidden,
            started_hotspot=False,
            method=result.method,
            on_creating=on_creating,
        )
        return

    # Show a "Scanning…" screen during the (~3s) scan so the UI doesn't sit on
    # the WiFi menu with no feedback, then replace it with the results list.
    store.dispatch(
        OpenRenderAction(
            kind='status',
            title='Scanning',
            props={
                'icon': '󰖩',
                'text': 'Scanning nearby networks…',
                'icon_size': 32,
                'text_font_size': 16,
            },
        ),
    )
    networks = await get_available_networks()
    _present_scan_menu(networks, on_creating, replace_top=True)


async def _headless_offline_flow(
    on_creating: Callable[[], None] | None,
) -> None:
    networks = await get_available_networks()
    try:
        _, result = await ubo_input(
            prompt='Select your WiFi network',
            descriptions=[network_select_description(networks)],
        )
    except asyncio.CancelledError:
        store.dispatch(WiFiStopHotspotAction())
        return
    except Exception:
        store.dispatch(WiFiStopHotspotAction())
        logger.exception('wifi connection input - error')
        raise

    choice = result.data.get('Network') if result else None
    if not choice:
        store.dispatch(WiFiStopHotspotAction())
        return
    if choice == OTHER_OPTION:
        await _connect_with_full_form(on_creating)
        return

    network = next((network for network in networks if network.ssid == choice), None)
    if network is None:
        await _connect_with_full_form(on_creating)
        return
    if network.type is WiFiType.NOPASS:
        # Open network: skip the password step, but the hotspot is already up.
        await _finalize_connection(
            network.ssid,
            '',
            WiFiType.NOPASS,
            hidden=False,
            started_hotspot=True,
            method=result.method,
            on_creating=on_creating,
        )
    else:
        await _connect_with_password_form(network, on_creating)


@store.with_state(
    # Guarded: the ip service may not be loaded (e.g. in focused flow tests);
    # treat unknown connectivity as not-connected so the caller falls back to
    # the ``has_gateway()`` route probe instead of crashing the Add flow.
    lambda state: state.ip.is_connected if hasattr(state, 'ip') else None,
)
def _store_reports_connected(is_connected: bool | None) -> bool:  # noqa: FBT001
    return bool(is_connected)


async def input_wifi_connection(
    *,
    input_methods: tuple[InputMethod, ...] = (),
    on_creating: Callable[[], None] | None = None,
) -> None:
    """Input WiFi connection."""
    logger.debug('wifi connection input - start')
    # Prefer the continuously-monitored, ping-based connectivity flag (immune to
    # the hotspot's own 192.168.4.1 link and to has_gateway()'s PATH/route-flush
    # flakiness); fall back to the route probe.
    route_present = _store_reports_connected() or await has_gateway()
    if route_present:
        await _route_present_flow(input_methods, on_creating)
    elif IS_UBO_POD:
        await _pod_offline_flow(input_methods, on_creating)
    else:
        await _headless_offline_flow(on_creating)
