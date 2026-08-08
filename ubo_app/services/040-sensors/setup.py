"""Setup the service."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import replace
from typing import TYPE_CHECKING

import board
import ha
from drivers import ACTIVE_SENSORS, ActiveSensor, UnsupportedDriverError, read_entities
from drivers import initialize_device as _initialize_device
from menu import init_menu, report_scan_result
from registry import load_registry
from scan import RESERVED_ADDRESSES, SensorMatch, builtin_matches, make_device_id
from scan import scan_and_match as _scan_and_match

from ubo_app.logger import logger
from ubo_app.store.core.view_registry import register_status_bar_dependency
from ubo_app.store.main import store
from ubo_app.store.services.mqtt import (
    MqttPublishAction,
    MqttRequestAnnounceAction,
)
from ubo_app.store.services.sensors import (
    Sensor,
    SensorDeviceState,
    SensorEntityReading,
    SensorsReportDeviceReadingsAction,
    SensorsReportReadingAction,
    SensorsScanCompletedAction,
    SensorsScanEvent,
    SensorStatus,
)
from ubo_app.utils.async_ import create_task
from ubo_app.utils.blocking_worker import BlockingWorker
from ubo_app.utils.error_handlers import report_service_error
from ubo_app.utils.mqtt_registry import (
    register_mqtt_components,
)
from ubo_app.utils.persistent_store import (
    read_from_persistent_store,
    register_persistent_store,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from adafruit_rgb_display.rgb import busio
    from registry import EntityDefinition, SensorDefinition

    from ubo_app.store.main import RootState
    from ubo_app.store.services.mqtt import MqttComponent
    from ubo_app.store.services.sensors import SensorsState
    from ubo_app.utils.types import Subscriptions

PERSISTENT_STORE_KEY = 'sensors_devices'

# Device id -> the legacy `Sensor` slot it feeds. Only the two on-board sensors
# appear here; it is what keeps `state.sensors.temperature` / `.light` — and so
# the status bar — working now that readings are per-device.
LEGACY_SENSORS: dict[str, Sensor] = {}

_i2c: busio.I2C | None = None
_definitions: tuple[SensorDefinition, ...] = ()

# Everything that touches the bus or `ACTIVE_SENSORS` goes through this: the
# poll loop, a re-scan and start-up initialization would otherwise overlap.
_hardware_lock = asyncio.Lock()

# Long enough for a full bus scan in which every driver exhausts its retries
# (five attempts a second apart, each). Past that the hardware is not slow, it
# is wedged. The number is a property of this bus, so it lives here rather than
# in the worker.
I2C_CALL_TIMEOUT = 60

# One thread owns the bus, shared by every instance of this service in this
# process — see `BlockingWorker`. Cancelling an await cannot stop a running
# hardware call, so a restarted instance queueing behind the old one is what
# stops two of them driving I²C at once.
WORKER = BlockingWorker('sensors-i2c', deadline=I2C_CALL_TIMEOUT)


def _bus() -> busio.I2C:
    """Return the shared I²C bus, which `init_service` opens."""
    if _i2c is None:
        msg = 'the I²C bus has not been initialized'
        raise RuntimeError(msg)
    return _i2c


def _activate(
    match: SensorMatch,
    previous: dict[str, ActiveSensor],
) -> SensorDeviceState:
    """Instantiate a matched sensor's driver and describe the outcome.

    A sensor `previous` already held at the same definition and address keeps
    its driver instance instead of being reconstructed — construction is not
    free: the SCD-40's constructor restarts its measurement cycle, which
    silences it for several seconds after every Refresh.
    """
    definition = match.definition
    if definition is None:
        return SensorDeviceState(
            id=make_device_id('', match.address),
            definition_id='',
            label=f'Unrecognized ({match.address:#04x})',
            address=match.address,
            is_builtin=match.is_builtin,
            status=SensorStatus.AMBIGUOUS,
        )

    device_id = make_device_id(definition.id, match.address)
    device = SensorDeviceState(
        id=device_id,
        definition_id=definition.id,
        label=definition.label,
        address=match.address,
        is_builtin=match.is_builtin,
        status=SensorStatus.ACTIVE,
    )

    existing = previous.get(device_id)
    if existing is not None:
        # Presence in the previous set means its driver initialized cleanly.
        ACTIVE_SENSORS[device_id] = existing
        return device

    try:
        instance = _initialize_device(definition, match.address, _bus())
    except UnsupportedDriverError:
        logger.warning(
            'Sensors: definition needs a driver this build does not ship',
            extra={
                'definition_id': definition.id,
                'driver_module': definition.driver.module,
            },
        )
        return replace(device, status=SensorStatus.UNSUPPORTED)
    except Exception:
        logger.exception(
            'Sensors: failed to initialize device',
            extra={'definition_id': definition.id, 'address': hex(match.address)},
        )
        # The explicit id matters: this runs on the worker thread, where
        # `get_service()` raises once the service has stopped — from inside
        # this except block, losing every device after the failing one.
        report_service_error(service_id='sensors')
        return replace(device, status=SensorStatus.ERROR)

    ACTIVE_SENSORS[device_id] = ActiveSensor(
        device_id=device_id,
        definition=definition,
        instance=instance,
    )
    return device


def _apply(matches: Sequence[SensorMatch]) -> tuple[SensorDeviceState, ...]:
    """Rebuild the active-sensor set from a fresh list of matches."""
    previous = dict(ACTIVE_SENSORS)
    ACTIVE_SENSORS.clear()
    return tuple(_activate(match, previous) for match in matches)


# Until this is set, the store's device list says nothing about the hardware —
# see `persistence_selector`.
_is_armed = False


def _arm_persistence() -> None:
    """Let the device list start being written out.

    Called once the store has been told what is actually on the bus, by
    whichever of the restore or a scan gets there first, and only when that
    succeeded.
    """
    global _is_armed  # noqa: PLW0603

    _is_armed = True


def _disarm_persistence() -> None:
    """Stop writing on shutdown, so a restarted instance re-arms from scratch."""
    global _is_armed  # noqa: PLW0603

    _is_armed = False


def persistence_selector(state: RootState) -> str | None:
    """Project the devices down to the identities worth persisting.

    `register_persistent_store` is an autorun, so it rewrites the persistent
    store whenever this selector's output changes. Readings must therefore stay
    out of it: including them would rewrite `state.json` — on the SD card —
    once a second, forever. Built-ins are excluded too; they come back from the
    EEPROM on every boot.

    `None` until the restore lands, and `register_persistent_store` skips a
    `None`. An autorun fires on its *initial* value, so a selector that
    answered honestly from the start would write an empty list over the very
    list the restore is still reading back in the worker thread.

    The gate is here, rather than in *when* the autorun is registered, because
    registering it later means registering it from a coroutine — and shutdown
    can run between the two, leaving an autorun bound to a service that has
    already been cleaned up. Registration stays synchronous in `init_service`,
    where its unsubscribe can be returned with the rest.
    """
    if not _is_armed:
        return None

    return json.dumps(
        [
            {'definition_id': device.definition_id, 'address': device.address}
            for device in sorted(
                state.sensors.devices.values(),
                key=lambda device: device.address,
            )
            if not device.is_builtin and device.definition_id
        ],
    )


def _persisted_matches(
    builtin_addresses: frozenset[int] = frozenset(),
) -> tuple[SensorMatch, ...]:
    """Re-attach sensors seen by the last scan, so a reboot needs no re-scan.

    Every entry is validated rather than trusted, on two counts.

    A hand-edited or truncated `state.json` must cost the user the sensors it
    describes, not the whole service — this runs during start-up, and raising
    would take `_initialize` with it.

    And an address here goes straight to a driver constructor, skipping the
    scan entirely. `scan.py` refuses to so much as *probe* the audio codec, the
    HAT EEPROM or the keypad expander, because a probe writes a register
    pointer and a stray byte to the codec is a partial register write. A
    persisted entry must clear the same bar: the address has to be one the
    definition actually claims, and must not belong to on-board hardware.
    """
    try:
        entries = read_from_persistent_store(
            PERSISTENT_STORE_KEY,
            mapper=json.loads,
            default=[],
        )
    except (json.JSONDecodeError, TypeError):
        # `TypeError` is `json.loads` refusing a stored value that is already a
        # real array rather than the JSON-encoded string this service writes.
        logger.warning('Sensors: unreadable persisted device list')
        return ()
    if not isinstance(entries, list):
        logger.warning('Sensors: persisted device list is not a list')
        return ()

    by_id = {definition.id: definition for definition in _definitions}

    matches: list[SensorMatch] = []
    seen_addresses: set[int] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        definition_id = entry.get('definition_id')
        if not isinstance(definition_id, str):
            continue
        definition = by_id.get(definition_id)
        if definition is None:
            # The definition went away with an update — it will come back on
            # the next scan if the sensor is still plugged in.
            continue
        address = entry.get('address')
        if (
            not isinstance(address, int)
            or isinstance(address, bool)
            or address not in definition.addresses
            or address in RESERVED_ADDRESSES
            or address in builtin_addresses
        ):
            logger.warning(
                'Sensors: refusing a persisted device at an unsafe address',
                extra={'entry': entry},
            )
            continue
        if address in seen_addresses:
            # Two entries resolving to one bus address would put two driver
            # instances' register traffic on one chip. The first wins — same
            # policy as `parse_registry` for duplicate ids.
            logger.warning(
                'Sensors: skipping a duplicate persisted address',
                extra={'entry': entry},
            )
            continue
        seen_addresses.add(address)
        matches.append(SensorMatch(address=address, definition=definition))
    return tuple(matches)


def _register_builtins() -> tuple[SensorMatch, ...]:
    """Resolve the on-board sensors and remember which legacy slot each feeds."""
    LEGACY_SENSORS.clear()
    matches: list[SensorMatch] = []
    for match, legacy_sensor in builtin_matches(_definitions):
        if match.definition is not None:
            device_id = make_device_id(match.definition.id, match.address)
            LEGACY_SENSORS[device_id] = legacy_sensor
        matches.append(match)
    return tuple(matches)


def _make_reading(
    key: str,
    value: float | None,
    definition: EntityDefinition | None,
) -> SensorEntityReading:
    """Pair a raw reading with its registry metadata for remote renderers."""
    if definition is None:
        return SensorEntityReading(key=key, value=value)
    return SensorEntityReading(
        key=key,
        value=value,
        name=definition.name,
        unit=definition.unit_of_measurement,
        device_class=definition.device_class,
        precision=definition.suggested_display_precision,
    )


def read_sensors() -> dict[str, dict[str, float | None]]:
    """Read every active device and report its entities.

    Runs in a worker thread. Returns the readings so the caller — back on the
    event loop — can hand them to the MQTT publisher; `asyncio.Queue` is not
    thread-safe, so the enqueue must not happen here.

    The two legacy `SensorsReportReadingAction`s go out alongside the
    per-device ones. They are what the status bar reads, and — exactly as
    before this became a device registry — they report 0.0 when the on-board
    sensor is absent, which is the case off-device.
    """
    legacy: dict[Sensor, float] = {Sensor.TEMPERATURE: 0.0, Sensor.LIGHT: 0.0}
    timestamp = time.time()
    all_readings: dict[str, dict[str, float | None]] = {}

    for device_id, sensor in list(ACTIVE_SENSORS.items()):
        readings = read_entities(sensor)
        all_readings[device_id] = readings
        definitions = {entity.key: entity for entity in sensor.definition.entities}
        store.dispatch(
            SensorsReportDeviceReadingsAction(
                device_id=device_id,
                entities=tuple(
                    _make_reading(key, value, definitions.get(key))
                    for key, value in readings.items()
                ),
                timestamp=timestamp,
            ),
        )

        legacy_slot = LEGACY_SENSORS.get(device_id)
        if legacy_slot is not None:
            # An on-board sensor has exactly one entity.
            value = next(iter(readings.values()), None)
            if value is not None:
                legacy[legacy_slot] = value

    store.dispatch(
        SensorsReportReadingAction(
            sensor=Sensor.TEMPERATURE,
            reading=legacy[Sensor.TEMPERATURE],
            timestamp=timestamp,
        ),
        SensorsReportReadingAction(
            sensor=Sensor.LIGHT,
            reading=legacy[Sensor.LIGHT],
            timestamp=timestamp,
        ),
    )

    return all_readings


@store.with_state(lambda state: state.sensors)
def _mqtt_components(sensors_state: SensorsState) -> list[MqttComponent]:
    """Describe the pod's sensors for Home Assistant.

    The MQTT bridge calls this whenever it (re)announces; it never sees this
    service's registry types, only Home Assistant's vocabulary.
    """
    return ha.components(
        tuple(sensors_state.devices.values()),
        {definition.id: definition for definition in _definitions},
    )


async def _monitor_sensors(end_event: asyncio.Event) -> None:
    while not end_event.is_set():
        try:
            # The same lock the scan takes: a re-scan rebuilds `ACTIVE_SENSORS`
            # and constructs drivers, so a poll running concurrently would read
            # a half-built registry and touch the I²C bus underneath it.
            async with _hardware_lock:
                # Shutdown can land while waiting for the lock — a stop during
                # a scan, say — and past this point the worker may already be
                # closed.
                if end_event.is_set():
                    return
                readings = await WORKER.run(read_sensors)
            for device_id, entities in readings.items():
                # A device whose every entity failed to read has nothing to
                # say. Publishing the all-null payload anyway would keep
                # resetting `expire_after` on the Home Assistant side, so a
                # sensor that has actually stopped working would report
                # `unknown` forever instead of going *unavailable* — which is
                # the state the user can act on.
                if all(value is None for value in entities.values()):
                    continue
                store.dispatch(
                    MqttPublishAction(
                        channel=ha.state_channel(device_id),
                        payload=json.dumps(entities),
                    ),
                )
        except Exception:
            # One flaky poll — a blown deadline, a wedged worker — must not end
            # monitoring for the rest of the service's life.
            logger.exception('Sensors: poll failed')
            report_service_error()
        await asyncio.sleep(1)


def _scan_and_activate() -> tuple[SensorDeviceState, ...]:
    """Scan the bus and bring up whatever is on it. Blocking — call in a thread.

    Scanning and driver initialization are one unit of work deliberately:
    `initialize_device` retries an `EIO` five times a second apart, so on the
    event loop a single flaky sensor would stall the service — including its
    shutdown — for five seconds.
    """
    builtins = _register_builtins()
    builtin_addresses = frozenset(match.address for match in builtins)

    # Deliberately unguarded: a bus failure is not "no sensors found". Turning
    # one into the other here would clear `ACTIVE_SENSORS`, replace the store's
    # devices with nothing, persist that, and retire every Home Assistant
    # entity — on a transient EIO. The caller keeps the previous registry
    # instead.
    scanned = _scan_and_match(
        _bus(),
        _definitions,
        RESERVED_ADDRESSES | builtin_addresses,
    )

    return _apply([*builtins, *scanned])


async def scan_sensors() -> None:
    """Scan the bus and rebuild the device registry.

    Completion is dispatched even when the scan blows up. `is_scanning` is what
    stops a second scan starting on top of this one, so failing without
    clearing it would leave Refresh permanently inert until a reboot. It
    carries `devices=None` in that case, which the reducer reads as "keep what
    we have" rather than "the bus is empty".
    """
    devices: tuple[SensorDeviceState, ...] | None = None
    try:
        async with _hardware_lock:
            devices = await WORKER.run(_scan_and_activate)
    except Exception:
        logger.exception('Sensors: scan failed')
        report_service_error()
    else:
        _arm_persistence()
    finally:
        store.dispatch(
            SensorsScanCompletedAction(devices=devices),
            # The entity set just changed — without this the bridge would keep
            # publishing readings for a sensor Home Assistant has never been
            # told about, until the next reconnect.
            MqttRequestAnnounceAction(),
        )

    report_scan_result(devices)


async def _handle_scan(_: SensorsScanEvent) -> None:
    await scan_sensors()


def _activate_persisted() -> tuple[SensorDeviceState, ...]:
    """Re-attach the sensors the last scan found. Blocking — call in a thread."""
    global _i2c  # noqa: PLW0603

    if _i2c is None:
        # Opened here, on the worker, rather than in `init_service`: one thread
        # owns the bus, and even opening it touches the hardware.
        _i2c = board.I2C()

    builtins = _register_builtins()
    builtin_addresses = frozenset(match.address for match in builtins)
    return _apply([*builtins, *_persisted_matches(builtin_addresses)])


async def _initialize() -> None:
    """Bring up the on-board sensors and re-attach previously seen ones.

    Guarded like `scan_sensors`: this is launched as a task from
    `init_service`, so a raise here would otherwise disappear into the task —
    no devices, no menu, no signal — and silently disable the whole service.
    """
    devices: tuple[SensorDeviceState, ...] | None = None
    try:
        async with _hardware_lock:
            devices = await WORKER.run(_activate_persisted)
            # Armed before the dispatch, not after: the dispatch is what
            # re-runs the persistence autorun, and this is the state it should
            # see.
            _arm_persistence()
            store.dispatch(
                SensorsScanCompletedAction(devices=devices),
                MqttRequestAnnounceAction(),
            )
            await WORKER.run(read_sensors)
    except Exception:
        logger.exception('Sensors: start-up activation failed')
        report_service_error()
        if devices is None:
            # `devices=None` is "keep what you have": it settles `is_scanning`
            # and the menu without pretending the bus is empty.
            store.dispatch(SensorsScanCompletedAction(devices=None))


def init_service() -> Subscriptions:
    """Initialize the service."""
    # Register view dependency for status bar temperature display
    unregister_temp = register_status_bar_dependency(
        'sensors:temp',
        lambda s: s.sensors.temperature.value if s.sensors.temperature else None,
    )

    global _definitions, WORKER  # noqa: PLW0603

    _definitions = load_registry()
    # A fresh instance, because the previous one's `aclose` latched it closed
    # and the loader may hand a restarted service this same module object. The
    # underlying thread is process-global per name either way — see
    # `BlockingWorker`.
    WORKER = BlockingWorker('sensors-i2c', deadline=I2C_CALL_TIMEOUT)

    unregister_menu = init_menu(
        {definition.id: definition for definition in _definitions},
    )

    create_task(_initialize())

    # Registered synchronously, so its unsubscribe is in the subscriptions
    # below rather than appearing at some point during start-up. What it
    # *writes* is gated by `_arm_persistence`.
    unregister_persistence = register_persistent_store(
        PERSISTENT_STORE_KEY,
        persistence_selector,
    )

    unregister_components = register_mqtt_components('sensors', _mqtt_components)

    end_event = asyncio.Event()
    create_task(_monitor_sensors(end_event))

    return [
        unregister_persistence,
        _disarm_persistence,
        end_event.set,
        WORKER.aclose,
        unregister_temp,
        unregister_components,
        *unregister_menu,
        store.subscribe_event(SensorsScanEvent, _handle_scan),
    ]
