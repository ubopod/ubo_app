"""Tests for the hardware-facing half of the sensors service.

`_apply`/`_activate` decide which driver instances exist, `read_sensors` feeds
the store, and `_monitor_sensors` is the 1 Hz loop that publishes. All of it is
exercised here with stubbed drivers — no bus — because the interesting failures
(a driver that raises, a poll that blows its deadline) are exactly the ones
that cannot be waited for on real hardware.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest
from fake import Fake

from tests.service_loader import load_service_modules
from ubo_app.store.services.sensors import Sensor, SensorStatus

# `setup` opens the I2C bus at import; off-device the app fakes `board` in
# `setup_headless`, and the test environment has to do the same.
sys.modules.setdefault('board', Fake())

drivers, registry, scan, setup = load_service_modules(
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '040-sensors',
    'drivers',
    'registry',
    'scan',
    'setup',
)


def _definition(definition_id: str = 'sht4x', address: int = 0x44) -> Any:  # noqa: ANN401
    return registry.SensorDefinition(
        id=definition_id,
        label=definition_id.upper(),
        manufacturer='X',
        addresses=(address,),
        driver=registry.DriverSpec(module='adafruit_sht4x', class_name='SHT4x'),
        entities=(
            registry.EntityDefinition(
                key='temperature',
                attribute='temperature',
                name='Temperature',
            ),
        ),
    )


def _match(definition_id: str = 'sht4x', address: int = 0x44) -> Any:  # noqa: ANN401
    return scan.SensorMatch(
        address=address,
        definition=_definition(definition_id, address),
    )


@pytest.fixture(autouse=True)
def _clean_registries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test with no live drivers and a fake bus."""
    setup.ACTIVE_SENSORS.clear()
    setup.LEGACY_SENSORS.clear()
    monkeypatch.setattr(setup, '_i2c', Fake())


@pytest.fixture
def dispatched(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Collect dispatched actions instead of driving the real store."""
    actions: list[Any] = []
    monkeypatch.setattr(
        setup.store,
        'dispatch',
        lambda *args: actions.extend(args),
    )
    # Reaches for the running service, which does not exist under pytest.
    monkeypatch.setattr(setup, 'report_service_error', lambda *_, **__: None)
    return actions


# --------------------------------------------------------------------------
# `_apply`: which driver instances exist after a (re-)scan
# --------------------------------------------------------------------------


def test_apply_rebuilds_the_active_set_from_the_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sensor absent from the new matches is gone — instance and all."""
    monkeypatch.setattr(setup, '_initialize_device', lambda *_: object())

    (device,) = setup._apply([_match()])  # noqa: SLF001
    assert device.status is SensorStatus.ACTIVE
    assert set(setup.ACTIVE_SENSORS) == {'sht4x_0x44'}

    assert setup._apply([]) == ()  # noqa: SLF001
    assert setup.ACTIVE_SENSORS == {}


def test_apply_reuses_an_unchanged_healthy_sensor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A re-scan must not reconstruct a driver that is already up.

    Construction is not free: the SCD-40's constructor restarts its measurement
    cycle, so a rebuilt instance publishes nothing for several seconds after
    every Refresh.
    """
    constructed: list[object] = []

    def _construct(*_: object) -> object:
        instance = object()
        constructed.append(instance)
        return instance

    monkeypatch.setattr(setup, '_initialize_device', _construct)

    setup._apply([_match()])  # noqa: SLF001
    first = setup.ACTIVE_SENSORS['sht4x_0x44']
    setup._apply([_match()])  # noqa: SLF001

    assert setup.ACTIVE_SENSORS['sht4x_0x44'] is first
    assert len(constructed) == 1


@pytest.mark.usefixtures('dispatched')
def test_apply_retries_a_sensor_that_failed_last_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reuse only applies to *healthy* sensors — a failed one gets another go."""
    attempts: list[object] = []

    def _flaky(*_: object) -> object:
        attempts.append(object())
        if len(attempts) == 1:
            msg = 'bus fell over'
            raise OSError(msg)
        return object()

    monkeypatch.setattr(setup, '_initialize_device', _flaky)

    (first,) = setup._apply([_match()])  # noqa: SLF001
    assert first.status is SensorStatus.ERROR
    assert setup.ACTIVE_SENSORS == {}

    (second,) = setup._apply([_match()])  # noqa: SLF001
    assert second.status is SensorStatus.ACTIVE
    assert set(setup.ACTIVE_SENSORS) == {'sht4x_0x44'}


# --------------------------------------------------------------------------
# The UNSUPPORTED / ERROR split
# --------------------------------------------------------------------------


def test_an_unshipped_driver_is_unsupported_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UNSUPPORTED means "update ubo-app" — a different remedy than ERROR."""

    def _unsupported(*_: object) -> object:
        module = 'adafruit_new_thing'
        raise drivers.UnsupportedDriverError(module)

    monkeypatch.setattr(setup, '_initialize_device', _unsupported)

    (device,) = setup._apply([_match()])  # noqa: SLF001

    assert device.status is SensorStatus.UNSUPPORTED
    assert setup.ACTIVE_SENSORS == {}


def test_a_driver_that_raises_is_an_error_and_names_the_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any other raise is ERROR, reported with an explicit service id.

    `_activate` runs on the worker thread, where `get_service()` raises once
    the service has stopped — from inside the except block, which would abort
    `_apply` and lose every device after the failing one.
    """
    reported: list[dict[str, object]] = []
    monkeypatch.setattr(
        setup,
        'report_service_error',
        lambda **kwargs: reported.append(kwargs),
    )

    def _fails(*_: object) -> object:
        msg = 'bus fell over'
        raise OSError(msg)

    monkeypatch.setattr(setup, '_initialize_device', _fails)

    (device,) = setup._apply([_match()])  # noqa: SLF001

    assert device.status is SensorStatus.ERROR
    assert setup.ACTIVE_SENSORS == {}
    assert reported == [{'service_id': 'sensors'}]


# --------------------------------------------------------------------------
# `read_sensors`: the legacy status-bar slots
# --------------------------------------------------------------------------


def _active(definition_id: str, address: int) -> Any:  # noqa: ANN401
    return drivers.ActiveSensor(
        device_id=f'{definition_id}_{address:#04x}',
        definition=_definition(definition_id, address),
        instance=object(),
    )


def test_read_sensors_feeds_only_builtins_into_the_legacy_slots(
    monkeypatch: pytest.MonkeyPatch,
    dispatched: list[Any],
) -> None:
    """An external sensor's temperature must not become the status bar's."""
    builtin = _active('pct2075', 0x48)
    external = _active('sht4x', 0x44)
    setup.ACTIVE_SENSORS.update(
        {builtin.device_id: builtin, external.device_id: external},
    )
    setup.LEGACY_SENSORS[builtin.device_id] = Sensor.TEMPERATURE

    readings = {
        'pct2075_0x48': {'temperature': 21.5},
        'sht4x_0x44': {'temperature': 30.0},
    }
    monkeypatch.setattr(
        setup,
        'poll_entities',
        lambda sensor, **_: dict(readings[sensor.device_id]),
    )

    assert setup.read_sensors() == readings

    per_device = [
        action.device_id
        for action in dispatched
        if type(action).__name__ == 'SensorsReportDeviceReadingsAction'
    ]
    assert sorted(per_device) == ['pct2075_0x48', 'sht4x_0x44']

    legacy = {
        action.sensor: action.reading
        for action in dispatched
        if type(action).__name__ == 'SensorsReportReadingAction'
    }
    assert legacy == {Sensor.TEMPERATURE: 21.5, Sensor.LIGHT: 0.0}


def test_read_sensors_attaches_registry_metadata_to_each_reading(
    monkeypatch: pytest.MonkeyPatch,
    dispatched: list[Any],
) -> None:
    """Readings carry their unit and label, so remote clients can render them.

    The registry never leaves the device, so a web or mobile client that only
    sees `SensorsState` has no other way to learn that `22.4` is degrees.
    """
    definition = registry.SensorDefinition(
        id='bme280',
        label='BME280',
        manufacturer='Bosch',
        addresses=(0x76,),
        driver=registry.DriverSpec(
            module='adafruit_bme280.basic',
            class_name='Adafruit_BME280_I2C',
        ),
        entities=(
            registry.EntityDefinition(
                key='temperature',
                attribute='temperature',
                name='Temperature',
                device_class='temperature',
                unit_of_measurement='°C',
                suggested_display_precision=1,
            ),
            # No metadata beyond a name — the reading must still go out.
            registry.EntityDefinition(
                key='gas_resistance',
                attribute='gas',
                name='Gas resistance',
            ),
        ),
    )
    sensor = drivers.ActiveSensor(
        device_id='bme280_0x76',
        definition=definition,
        instance=object(),
    )
    setup.ACTIVE_SENSORS['bme280_0x76'] = sensor
    monkeypatch.setattr(
        setup,
        'poll_entities',
        lambda _sensor, **_: {'temperature': 22.4, 'gas_resistance': 51000.0},
    )

    setup.read_sensors()

    action = next(
        action
        for action in dispatched
        if type(action).__name__ == 'SensorsReportDeviceReadingsAction'
    )
    entities = {entity.key: entity for entity in action.entities}

    assert entities['temperature'].value == 22.4
    assert entities['temperature'].name == 'Temperature'
    assert entities['temperature'].unit == '°C'
    assert entities['temperature'].device_class == 'temperature'
    assert entities['temperature'].precision == 1

    assert entities['gas_resistance'].value == 51000.0
    assert entities['gas_resistance'].name == 'Gas resistance'
    assert entities['gas_resistance'].unit is None
    assert entities['gas_resistance'].device_class is None
    assert entities['gas_resistance'].precision is None


def test_read_sensors_reports_zero_for_an_absent_builtin(
    dispatched: list[Any],
) -> None:
    """Exactly as before the device registry: off-device the legacy slots are 0.0."""
    assert setup.read_sensors() == {}

    legacy = {
        action.sensor: action.reading
        for action in dispatched
        if type(action).__name__ == 'SensorsReportReadingAction'
    }
    assert legacy == {Sensor.TEMPERATURE: 0.0, Sensor.LIGHT: 0.0}


# --------------------------------------------------------------------------
# `_monitor_sensors`: the 1 Hz poll loop
# --------------------------------------------------------------------------


@pytest.fixture
def _fast_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    """Collapse the loop's 1 s pacing so a test can run several iterations."""
    real_sleep = asyncio.sleep

    async def _no_wait(_delay: float) -> None:
        await real_sleep(0)

    monkeypatch.setattr(setup.asyncio, 'sleep', _no_wait)


@pytest.mark.usefixtures('_fast_poll')
async def test_a_device_with_nothing_to_say_is_not_published(
    monkeypatch: pytest.MonkeyPatch,
    dispatched: list[Any],
) -> None:
    """An all-null payload would keep resetting `expire_after`.

    Home Assistant would then show a dead sensor as `unknown` forever instead
    of taking it `unavailable` — the state the user can act on.
    """
    end_event = asyncio.Event()

    async def _reads(*_: object, **__: object) -> dict[str, dict[str, float | None]]:
        end_event.set()
        return {
            'sht4x_0x44': {'temperature': None},
            'bme280_0x76': {'temperature': 21.0, 'humidity': None},
        }

    monkeypatch.setattr(setup.WORKER, 'run', _reads)

    await asyncio.wait_for(setup._monitor_sensors(end_event), timeout=5)  # noqa: SLF001

    publishes = [
        action
        for action in dispatched
        if type(action).__name__ == 'MqttPublishAction'
    ]
    assert [action.channel for action in publishes] == ['bme280_0x76/state']


@pytest.mark.usefixtures('_fast_poll')
async def test_a_failed_poll_does_not_end_monitoring(
    monkeypatch: pytest.MonkeyPatch,
    dispatched: list[Any],
) -> None:
    """One flaky read must not kill polling for the life of the service.

    `BlockingWorker.run` raises `TimeoutError` on a blown deadline; without the
    guard that single raise would silently end the loop.
    """
    _ = dispatched
    end_event = asyncio.Event()
    calls: list[int] = []

    async def _flaky(*_: object, **__: object) -> dict[str, dict[str, float | None]]:
        calls.append(len(calls))
        if len(calls) == 1:
            msg = 'sensors-i2c exceeded its 60s deadline'
            raise TimeoutError(msg)
        end_event.set()
        return {}

    monkeypatch.setattr(setup.WORKER, 'run', _flaky)

    await asyncio.wait_for(setup._monitor_sensors(end_event), timeout=5)  # noqa: SLF001

    assert len(calls) == 2


async def test_a_stop_while_waiting_for_the_lock_never_reaches_the_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shutdown during a scan: past the lock the worker may already be closed."""
    end_event = asyncio.Event()
    ran: list[object] = []

    async def _runs(*args: object, **__: object) -> dict[str, dict[str, float | None]]:
        ran.append(args)
        return {}

    monkeypatch.setattr(setup.WORKER, 'run', _runs)

    async with setup._hardware_lock:  # noqa: SLF001
        monitor = asyncio.ensure_future(setup._monitor_sensors(end_event))  # noqa: SLF001
        # Let the loop start and block on the lock this test is holding.
        await asyncio.sleep(0)
        end_event.set()

    await asyncio.wait_for(monitor, timeout=5)

    assert ran == []
