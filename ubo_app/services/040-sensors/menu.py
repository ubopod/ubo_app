"""The Sensors settings menu, and the per-sensor readings page.

Two autoruns, deliberately split. The device list reacts to a *projection* of
the sensor state that holds only identities, so it does not re-render every
time a reading lands; the readings page reacts to the readings themselves,
where updating once a second is the whole point.

Selecting a sensor opens a `readings` render view — a label/value/unit table —
rather than a submenu, because a menu row is a single line of text with nowhere
to put a value or a unit.
"""

from __future__ import annotations

import functools
import math
from typing import TYPE_CHECKING, NamedTuple

from ubo_app.colors import DANGER_COLOR, SUCCESS_COLOR, WARNING_COLOR
from ubo_app.store.core.action_registry import (
    get_registered_actions,
    register_action,
    unregister_action,
)
from ubo_app.store.core.types import (
    MenuItemData,
    OpenRenderAction,
    RegisterSettingAppAction,
    RenderStackItem,
    SettingsCategory,
    UpdateDynamicMenuAction,
    UpdateRenderPropsAction,
)
from ubo_app.store.core.view_registry import register_path_menu_matcher
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.sensors import (
    SensorsScanAction,
    SensorStatus,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from registry import SensorDefinition

    from ubo_app.store.main import RootState
    from ubo_app.store.services.sensors import SensorDeviceState, SensorsState
    from ubo_app.store.ubo_actions import BasicType

    RenderProps = dict[
        str,
        BasicType | tuple[BasicType, ...] | list[BasicType],
    ]

SENSORS_MENU_ID = 'sensors:settings'
SETTINGS_PATH_KEY = 'sensors:'
SCAN_NOTIFICATION_ID = 'sensors_scan'

_SETTINGS_PATH_LENGTH = 4

UNKNOWN_VALUE = '—'
_DEFAULT_PRECISION = 1

# Entity metadata — display names, units, precision — lives in the registry, not
# in the store: `SensorEntityReading` carries only a key and a number.
_definitions: Mapping[str, SensorDefinition] = {}

_STATUS_ICONS = {
    SensorStatus.ACTIVE: '󰄬',
    SensorStatus.ERROR: '󰜺',
    SensorStatus.UNSUPPORTED: '󰛨',
    SensorStatus.AMBIGUOUS: '󰋗',
}

# Shown instead of readings, for a device that has none to give.
_STATUS_HINTS = {
    SensorStatus.ERROR: 'Failed to initialize',
    SensorStatus.UNSUPPORTED: 'Update ubo-app to use this sensor',
    SensorStatus.AMBIGUOUS: 'Could not identify this device',
}


class _Identity(NamedTuple):
    """What the device list renders — everything but the readings."""

    id: str
    definition_id: str
    label: str
    status: SensorStatus
    address: int
    is_builtin: bool


_STREAM_PREFIX = 'sensors:readings:'


def _stream_id(device_id: str) -> str:
    """Identify one sensor's readings page, so updates find the open one."""
    return f'{_STREAM_PREFIX}{device_id}'


def _path_matcher(path: tuple[str, ...]) -> str | None:
    """Resolve the Sensors device list.

    A sensor's readings are a render view, not a menu, so there is no deeper
    path to match.
    """
    if len(path) < _SETTINGS_PATH_LENGTH or path[3] != SETTINGS_PATH_KEY:
        return None
    return SENSORS_MENU_ID


def _format_value(value: float | None, precision: int | None) -> str:
    """Render a reading for the screen.

    The registry knows each entity's display precision — showing a CO2 reading
    as `412.00 ppm` or a pressure as `1013 hPa` would both be wrong.
    """
    if value is None:
        return UNKNOWN_VALUE
    digits = _DEFAULT_PRECISION if precision is None else precision
    return f'{value:.{digits}f}'


def _reading_rows(
    device: SensorDeviceState,
) -> tuple[
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    """Build the parallel label/value/unit/key/device_class readings rows.

    `key` and `device_class` let a rich client look up the same icon+range
    table (`SensorDisplay`/its Kotlin counterpart) the Dashboard's sensor
    tiles already use, instead of guessing from the label text.
    """
    definition = _definitions.get(device.definition_id)
    readings = {entity.key: entity.value for entity in device.entities}

    if definition is None:
        # No definition (a registry change dropped it): fall back to raw keys
        # rather than showing the user nothing.
        return (
            tuple(entity.key for entity in device.entities),
            tuple(_format_value(entity.value, None) for entity in device.entities),
            tuple('' for _ in device.entities),
            tuple(entity.key for entity in device.entities),
            tuple('' for _ in device.entities),
        )

    return (
        tuple(entity.name for entity in definition.entities),
        tuple(
            _format_value(
                readings.get(entity.key),
                entity.suggested_display_precision,
            )
            for entity in definition.entities
        ),
        tuple(
            entity.unit_of_measurement or '' for entity in definition.entities
        ),
        tuple(entity.key for entity in definition.entities),
        tuple(entity.device_class or '' for entity in definition.entities),
    )


def _identities(state: SensorsState) -> tuple[_Identity, ...]:
    """Project the devices to their identities, built-ins first then by address.

    Dropping the readings here is what stops the device-list autorun from
    re-rendering once a second.
    """
    return tuple(
        _Identity(
            id=device.id,
            definition_id=device.definition_id,
            label=device.label,
            status=device.status,
            address=device.address,
            is_builtin=device.is_builtin,
        )
        for device in sorted(
            state.devices.values(),
            key=lambda device: (not device.is_builtin, device.address),
        )
    )


def _open_device(identity: _Identity) -> None:
    """Open a sensor: its live readings, or why it has none."""
    hint = _STATUS_HINTS.get(identity.status)
    if hint is not None:
        store.dispatch(
            OpenRenderAction(
                kind='status',
                title=identity.label,
                props={
                    'icon': _STATUS_ICONS.get(identity.status, '󰋗'),
                    'text': hint,
                },
            ),
        )
        return

    definition = _definitions.get(identity.definition_id)
    entities = definition.entities if definition else ()

    # Labels/units/keys/device_classes are the page's structure and are known
    # up front; the values arrive from the poll loop within the second.
    props: RenderProps = {
        'labels': tuple(entity.name for entity in entities),
        'values': tuple(UNKNOWN_VALUE for _ in entities),
        'units': tuple(entity.unit_of_measurement or '' for entity in entities),
        'keys': tuple(entity.key for entity in entities),
        'device_classes': tuple(entity.device_class or '' for entity in entities),
    }
    store.dispatch(
        OpenRenderAction(
            kind='readings',
            title=identity.label,
            props=props,
            stream_id=_stream_id(identity.id),
        ),
    )


def _register_device_actions(identities: tuple[_Identity, ...]) -> None:
    """Register one action per device row."""
    for action_id in list(get_registered_actions()):
        if action_id.startswith('sensors:open:'):
            unregister_action(action_id)

    for identity in identities:
        register_action(
            f'sensors:open:{identity.id}',
            functools.partial(_open_device, identity),
        )


def _scan() -> None:
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=SCAN_NOTIFICATION_ID,
                title='Sensors',
                content='Scanning the I²C bus ...',
                display_type=NotificationDisplayType.STICKY,
                color=WARNING_COLOR,
                icon='󰍉',
                show_dismiss_action=False,
                progress=math.nan,
            ),
        ),
        SensorsScanAction(),
    )


def report_scan_result(devices: tuple[SensorDeviceState, ...] | None) -> None:
    """Replace the sticky scanning notification with the outcome.

    `None` is a failed scan, which must not read as "no sensors found" — the
    sensors the user has plugged in are still attached and still reporting.
    """
    if devices is None:
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id=SCAN_NOTIFICATION_ID,
                    title='Sensors',
                    content='Scan failed. Kept the sensors already attached.',
                    display_type=NotificationDisplayType.FLASH,
                    color=DANGER_COLOR,
                    icon='󰜺',
                    chime=Chime.FAILURE,
                ),
            ),
        )
        return

    found = [device for device in devices if not device.is_builtin]
    content = (
        f'Found {len(found)} sensor{"" if len(found) == 1 else "s"}'
        if found
        else 'No external sensors found'
    )
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=SCAN_NOTIFICATION_ID,
                title='Sensors',
                content=content,
                display_type=NotificationDisplayType.FLASH,
                color=SUCCESS_COLOR,
                icon='󰄬',
                chime=Chime.DONE,
            ),
        ),
    )


def _update_device_list(identities: tuple[_Identity, ...]) -> None:
    """Render the device list."""
    _register_device_actions(identities)

    items = [
        MenuItemData(
            key='sensors:scan',
            label='Refresh',
            icon='󰑐',
            action_id='sensors:scan',
        ),
        *(
            MenuItemData(
                key=identity.id,
                label=identity.label,
                icon=_STATUS_ICONS.get(identity.status, '󰋗'),
                action_id=f'sensors:open:{identity.id}',
            )
            for identity in identities
        ),
    ]

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=SENSORS_MENU_ID,
            title='Sensors',
            heading='Sensors',
            sub_heading=(
                f'{len(identities)} connected'
                if identities
                else 'Press Refresh to scan the bus'
            ),
            items=tuple(items),
            placeholder='No sensors. Press Refresh to scan.',
        ),
    )


def _open_readings(
    state: RootState,
) -> tuple[
    str,
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
] | None:
    """Select the rows of the readings page on screen, if one is open.

    Selecting only the open page's rows is what keeps this linear. Every sensor
    dispatches its own reading each second, and each of those replaces
    `state.sensors.devices` — so an autorun over the whole mapping would wake on
    all N and, if it then dispatched per device, produce N² actions a second
    whether or not anyone was looking at a sensor.

    Only the *top* of the stack counts: a readings page buried under a
    notification is not on screen, and pushing 1 Hz updates to it anyway would
    re-render every connected client for a page nobody can see.
    """
    if not state.main.stack:
        return None
    item = state.main.stack[-1]
    if (
        not isinstance(item, RenderStackItem)
        or not item.stream_id.startswith(_STREAM_PREFIX)
    ):
        return None
    device = state.sensors.devices.get(
        item.stream_id.removeprefix(_STREAM_PREFIX),
    )
    if device is None or device.status is not SensorStatus.ACTIVE:
        return None
    return (item.stream_id, *_reading_rows(device))


def _update_open_readings(
    rows: tuple[
        str,
        tuple[str, ...],
        tuple[str, ...],
        tuple[str, ...],
        tuple[str, ...],
        tuple[str, ...],
    ] | None,
) -> None:
    """Push the open page's latest readings, at the 1 Hz poll rate."""
    if rows is None:
        return

    stream_id, labels, values, units, keys, device_classes = rows
    props: RenderProps = {
        'labels': labels,
        'values': values,
        'units': units,
        'keys': keys,
        'device_classes': device_classes,
    }
    store.dispatch(
        UpdateRenderPropsAction(stream_id=stream_id, props=props),
    )


def _unregister_actions() -> None:
    """Drop every action this module owns, including the per-device ones.

    Without it a stopped service leaves handlers behind that dispatch into
    reducers which no longer exist.
    """
    for action_id in list(get_registered_actions()):
        if action_id == 'sensors:scan' or action_id.startswith('sensors:open:'):
            unregister_action(action_id)


def init_menu(
    definitions: Mapping[str, SensorDefinition],
) -> list[Callable[[], None]]:
    """Register the Sensors settings app, its path matcher and its actions."""
    global _definitions  # noqa: PLW0603

    _definitions = definitions

    store.dispatch(
        RegisterSettingAppAction(
            priority=1,
            category=SettingsCategory.HARDWARE,
            label='Sensors',
            icon='󰡵',
        ),
    )

    register_action('sensors:scan', _scan, allow_reregister=True)

    # Subscribed here rather than at import: a module-level `@store.autorun`
    # registers a listener the moment the file is imported, which leaks one per
    # import in tests and survives a failed `init_service` in production.
    device_list = store.autorun(lambda state: _identities(state.sensors))(
        _update_device_list,
    )
    open_readings = store.autorun(_open_readings)(_update_open_readings)

    return [
        register_path_menu_matcher('sensors:settings', _path_matcher),
        _unregister_actions,
        device_list.unsubscribe,
        open_readings.unsubscribe,
    ]
