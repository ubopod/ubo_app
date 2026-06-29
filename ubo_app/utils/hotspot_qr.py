"""Shared Wi-Fi-hotspot QR helpers.

The hotspot's join QR (SSID + password) is a hotspot artifact shown from two
places: the wifi service's toggle-on "connect" notification and the web-ui
service's captive pending-input notification. Keeping these pure helpers in
``utils`` lets both services use them without depending on each other's slice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.constants import WEB_UI_HOTSPOT_PASSWORD
from ubo_app.store.core.types import OpenRenderAction
from ubo_app.store.services.notifications import NotificationDispatchItem
from ubo_app.utils.pod_id import get_pod_id

if TYPE_CHECKING:
    from ubo_app.store.core.types.stack_items import StackItemType

HOTSPOT_QR_STREAM_ID = 'web_ui:hotspot-qr'


def _escape_wifi_qr(value: str) -> str:
    # Escape the WiFi-QR special characters; backslash first to avoid double-escaping.
    for char in ('\\', ';', ',', ':', '"'):
        value = value.replace(char, '\\' + char)
    return value


def build_wifi_qr(ssid: str, password: str) -> str:
    """Build a standard WiFi-join QR payload (WPA) for the hotspot."""
    return f'WIFI:S:{_escape_wifi_qr(ssid)};T:WPA;P:{_escape_wifi_qr(password)};;'


def hotspot_qr_action() -> NotificationDispatchItem:
    """Build a notification button that shows a WiFi-join QR for the hotspot."""
    pod_id = get_pod_id(with_default=True)
    return NotificationDispatchItem(
        key='hotspot-qr',
        label='WiFi QR',
        icon='󰐲',
        store_action=OpenRenderAction(
            kind='qr_code',
            title='Join Hotspot',
            props={
                'value': build_wifi_qr(pod_id, WEB_UI_HOTSPOT_PASSWORD),
                'label': pod_id,
            },
            stream_id=HOTSPOT_QR_STREAM_ID,
        ),
        # Keep the notification on the stack so pressing BACK on the QR page
        # returns to it (instructions), instead of dismissing it.
        dismiss_notification=False,
        close_notification=False,
    )


def pop_hotspot_qr_render() -> None:
    """Pop the hotspot QR render frame if it is on the stack (no-op otherwise)."""
    # Imported lazily so the pure QR builders above stay importable without
    # creating the store (keeps unit tests light).
    from ubo_app.store.core.types import StackPopItemAction
    from ubo_app.store.core.types.stack_items import RenderStackItem
    from ubo_app.store.main import store

    @store.with_state(lambda state: state.main.stack)
    def _pop(stack: tuple[StackItemType, ...]) -> None:
        qr = next(
            (
                item
                for item in stack
                if isinstance(item, RenderStackItem)
                and item.stream_id == HOTSPOT_QR_STREAM_ID
            ),
            None,
        )
        if qr is not None:
            store.dispatch(StackPopItemAction(item_id=qr.id))

    _pop()
