"""Tests for reading entities off a driver instance.

Most drivers expose one property per entity. The PMSA003I instead returns
everything from a single ``read()`` call — and each call consumes a fresh frame
from the sensor, so calling it once per entity would be wrong as well as
wasteful.
"""

from __future__ import annotations

import errno
from pathlib import Path
from typing import Any

from tests.service_loader import load_service_modules

registry, drivers = load_service_modules(
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '040-sensors',
    'registry',
    'drivers',
)


class _PropertySensor:
    """A driver of the usual shape: one property per entity."""

    temperature = 21.5
    relative_humidity = 40.0


class _MappingSensor:
    """A PMSA003I-shaped driver: every value from one `read()` call."""

    def __init__(self, data: dict[str, Any] | Exception) -> None:
        self.data = data
        self.calls = 0

    def read(self) -> dict[str, Any]:
        self.calls += 1
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


class _PrimedSensor:
    """An ENS160-shaped driver: data appears only after the status flag is read.

    `read_all_sensors()` returns the buffer, but the buffer is empty until
    `new_data_available` (a property) has been touched to latch a fresh sample.
    """

    def __init__(self, fresh: dict[str, Any]) -> None:
        self._fresh = fresh
        self._buffer: dict[str, Any] = dict.fromkeys(fresh)
        self.primed = 0

    @property
    def new_data_available(self) -> bool:
        self.primed += 1
        self._buffer = dict(self._fresh)
        return True

    def read_all_sensors(self) -> dict[str, Any]:
        return self._buffer

    @property
    def data_validity(self) -> int:
        """A live status register, deliberately *not* part of the buffer."""
        return 2


def _definition(
    *,
    entities: tuple[tuple[str, str], ...],
    read_method: str | None = None,
    read_primer: str | None = None,
    min_read_interval: float = 0.0,
) -> Any:  # noqa: ANN401
    return registry.SensorDefinition(
        id='test',
        label='Test',
        manufacturer='ACME',
        addresses=(0x12,),
        min_read_interval=min_read_interval,
        driver=registry.DriverSpec(
            module='adafruit_pm25.i2c',
            class_name='PM25_I2C',
            read_method=read_method,
            read_primer=read_primer,
        ),
        entities=tuple(
            registry.EntityDefinition(key=key, attribute=attribute, name=key)
            for key, attribute in entities
        ),
    )


def _sensor(definition: Any, instance: Any) -> Any:  # noqa: ANN401
    return drivers.ActiveSensor(
        device_id='test_0x12',
        definition=definition,
        instance=instance,
    )


def test_property_driver_is_read_attribute_by_attribute() -> None:
    """The usual shape: each entity names a property."""
    definition = _definition(
        entities=(('temperature', 'temperature'), ('humidity', 'relative_humidity')),
    )

    readings = drivers.read_entities(_sensor(definition, _PropertySensor()))

    assert readings == {'temperature': 21.5, 'humidity': 40.0}


def test_mapping_driver_is_read_exactly_once_per_poll() -> None:
    """`read()` consumes a frame, so it must be called once — not once per entity."""
    definition = _definition(
        entities=(('pm1', 'pm10 standard'), ('pm25', 'pm25 standard')),
        read_method='read',
    )
    instance = _MappingSensor({'pm10 standard': 3, 'pm25 standard': 7})

    readings = drivers.read_entities(_sensor(definition, instance))

    assert instance.calls == 1
    assert readings == {'pm1': 3.0, 'pm25': 7.0}


def test_mapping_driver_survives_a_corrupt_frame() -> None:
    """The PM25 driver raises RuntimeError on a bad checksum; that is not fatal.

    A corrupt frame means "no reading this second", not a dead sensor.
    """
    definition = _definition(
        entities=(('pm1', 'pm10 standard'), ('pm25', 'pm25 standard')),
        read_method='read',
    )
    instance = _MappingSensor(RuntimeError('Invalid PM2.5 checksum'))

    readings = drivers.read_entities(_sensor(definition, instance))

    assert readings == {'pm1': None, 'pm25': None}


def test_mapping_driver_tolerates_a_missing_key() -> None:
    """One absent key must not cost the other entities their readings."""
    definition = _definition(
        entities=(('pm1', 'pm10 standard'), ('pm25', 'pm25 standard')),
        read_method='read',
    )
    instance = _MappingSensor({'pm25 standard': 7})

    readings = drivers.read_entities(_sensor(definition, instance))

    assert readings == {'pm1': None, 'pm25': 7.0}


def test_read_primer_latches_a_fresh_sample_before_the_read() -> None:
    """The ENS160 presents data only after its status flag is read each poll."""
    definition = _definition(
        entities=(('eco2', 'eCO2'), ('tvoc', 'TVOC'), ('aqi', 'AQI')),
        read_method='read_all_sensors',
        read_primer='new_data_available',
    )
    instance = _PrimedSensor({'eCO2': 411, 'TVOC': 26, 'AQI': 1})

    readings = drivers.read_entities(_sensor(definition, instance))

    assert instance.primed == 1
    assert readings == {'eco2': 411.0, 'tvoc': 26.0, 'aqi': 1.0}


def test_without_a_primer_the_ens160_buffer_reads_empty() -> None:
    """Without the primer the buffer stays empty — which is why the primer exists."""
    definition = _definition(
        entities=(('eco2', 'eCO2'),),
        read_method='read_all_sensors',
    )
    instance = _PrimedSensor({'eCO2': 411})

    readings = drivers.read_entities(_sensor(definition, instance))

    assert instance.primed == 0
    assert readings == {'eco2': None}


def test_shipped_ens160_uses_a_primed_mapping_read() -> None:
    """Pin the shipped definition's shape: it must prime, then read a mapping."""
    definitions = {
        definition.id: definition for definition in registry.load_registry()
    }
    driver = definitions['ens160'].driver

    assert driver.read_method == 'read_all_sensors'
    assert driver.read_primer == 'new_data_available'


def test_pmsa003i_particulate_sizes_are_not_transposed() -> None:
    """Plantower's key names are a trap, and getting them wrong misreports air quality.

    In the PMS frame, `pm10 standard` is PM1.0 (one micrometre) and
    `pm100 standard` is PM10 (ten micrometres) — NOT the other way round. This
    pins the shipped definition against that.
    """
    definitions = {
        definition.id: definition for definition in registry.load_registry()
    }
    pmsa003i = definitions['pmsa003i']

    by_key = {entity.key: entity for entity in pmsa003i.entities}

    assert by_key['pm1'].attribute == 'pm10 standard'
    assert by_key['pm1'].device_class == 'pm1'

    assert by_key['pm25'].attribute == 'pm25 standard'
    assert by_key['pm25'].device_class == 'pm25'

    assert by_key['pm10'].attribute == 'pm100 standard'
    assert by_key['pm10'].device_class == 'pm10'


def test_pmsa003i_reads_a_realistic_frame() -> None:
    """End-to-end over the shipped definition, against a real PMS frame's keys."""
    definitions = {
        definition.id: definition for definition in registry.load_registry()
    }
    instance = _MappingSensor(
        {
            'pm10 standard': 4,
            'pm25 standard': 6,
            'pm100 standard': 7,
            'pm10 env': 4,
            'pm25 env': 6,
            'pm100 env': 7,
            'particles 03um': 700,
        },
    )

    readings = drivers.read_entities(_sensor(definitions['pmsa003i'], instance))

    assert readings == {'pm1': 4.0, 'pm25': 6.0, 'pm10': 7.0}
    assert instance.calls == 1


def test_a_mapping_driver_entity_may_still_come_off_the_instance() -> None:
    """Not everything such a driver exposes is in the mapping.

    The ENS160 buffers its measurements into `read_all_sensors()`, but reports
    data validity from a status register read live off the instance — and that
    state is exactly what says whether the buffered numbers mean anything.
    """
    definition = _definition(
        entities=(('eco2', 'eCO2'), ('validity', 'data_validity')),
        read_method='read_all_sensors',
        read_primer='new_data_available',
    )

    readings = drivers.read_entities(
        _sensor(definition, _PrimedSensor({'eCO2': 400})),
    )

    assert readings == {'eco2': 400.0, 'validity': 2.0}


class _CountingSensor:
    """A property-shaped driver that counts how often the bus was touched."""

    def __init__(self, *, fails: bool = False) -> None:
        self.reads = 0
        self.fails = fails

    @property
    def temperature(self) -> float:
        self.reads += 1
        if self.fails:
            # A wedged bus surfaces as EREMOTEIO (121) on the device, but that
            # errno does not exist on every platform this suite runs on — and
            # an `AttributeError` for the missing constant is itself caught by
            # the read path, which would pass this test for the wrong reason.
            msg = 'Remote I/O error'
            raise OSError(errno.EIO, msg)
        return 21.5


def test_a_sensor_without_an_interval_is_polled_every_tick() -> None:
    """The default must stay "ask every second" — most sensors want that."""
    instance = _CountingSensor()
    sensor = _sensor(_definition(entities=(('t', 'temperature'),)), instance)

    for tick in range(3):
        drivers.poll_entities(sensor, now=float(tick))

    assert instance.reads == 3


def test_a_slow_sensor_is_kept_off_the_bus_between_measurements() -> None:
    """Polling faster than the sensor measures is pure bus traffic.

    The reading the driver would return in between is the one it already
    returned, so serving it from our own cache changes nothing a consumer can
    see — it only stops the round trip.
    """
    instance = _CountingSensor()
    sensor = _sensor(
        _definition(entities=(('t', 'temperature'),), min_read_interval=5),
        instance,
    )

    first = drivers.poll_entities(sensor, now=0.0)
    within = [drivers.poll_entities(sensor, now=now) for now in (1.0, 2.0, 4.9)]

    assert instance.reads == 1
    assert first == {'t': 21.5}
    assert all(reading == {'t': 21.5} for reading in within)


def test_a_slow_sensor_is_read_again_once_its_interval_elapses() -> None:
    """The gate delays the read; it must not cancel it."""
    instance = _CountingSensor()
    sensor = _sensor(
        _definition(entities=(('t', 'temperature'),), min_read_interval=5),
        instance,
    )

    drivers.poll_entities(sensor, now=0.0)
    drivers.poll_entities(sensor, now=2.0)
    drivers.poll_entities(sensor, now=5.0)

    assert instance.reads == 2


def test_a_totally_failed_read_backs_off_instead_of_retrying_every_tick() -> None:
    """A wedged bus outlives a tick by minutes; 1 Hz retries just add to it.

    A slave holding SDA low takes every other device down with it, so hammering
    the one that failed makes the whole bus worse, not better.
    """
    instance = _CountingSensor(fails=True)
    sensor = _sensor(_definition(entities=(('t', 'temperature'),)), instance)

    readings = [drivers.poll_entities(sensor, now=float(tick)) for tick in range(4)]

    assert instance.reads < 4
    assert all(reading == {'t': None} for reading in readings)


def test_backoff_grows_with_each_consecutive_failure() -> None:
    """Two failures in a row must wait longer than one did."""
    instance = _CountingSensor(fails=True)
    sensor = _sensor(_definition(entities=(('t', 'temperature'),)), instance)

    drivers.poll_entities(sensor, now=0.0)
    first_delay = sensor.next_read_at
    drivers.poll_entities(sensor, now=first_delay)
    second_delay = sensor.next_read_at - first_delay

    assert second_delay > first_delay


def test_backoff_is_capped_so_a_recovered_sensor_comes_back() -> None:
    """Unbounded doubling would strand a sensor that fixed itself."""
    instance = _CountingSensor(fails=True)
    sensor = _sensor(_definition(entities=(('t', 'temperature'),)), instance)

    now = 0.0
    for _ in range(20):
        drivers.poll_entities(sensor, now=now)
        now = sensor.next_read_at

    assert sensor.next_read_at - now <= drivers.BACKOFF_MAX_SECONDS


def test_a_successful_read_clears_the_backoff() -> None:
    """One good read means the bus is back; resume the normal cadence."""
    instance = _CountingSensor(fails=True)
    sensor = _sensor(_definition(entities=(('t', 'temperature'),)), instance)

    drivers.poll_entities(sensor, now=0.0)
    instance.fails = False
    recovered_at = sensor.next_read_at
    readings = drivers.poll_entities(sensor, now=recovered_at)

    assert readings == {'t': 21.5}
    assert sensor.consecutive_failures == 0
    # No interval to serve out, so it is due again on the very next tick.
    assert sensor.next_read_at <= recovered_at


def test_a_partly_readable_sensor_is_not_treated_as_failed() -> None:
    """One dead register is not a dead device — it still has something to say."""
    definition = _definition(
        entities=(('t', 'temperature'), ('missing', 'nonexistent')),
    )
    instance = _CountingSensor()
    sensor = _sensor(definition, instance)

    drivers.poll_entities(sensor, now=0.0)
    drivers.poll_entities(sensor, now=1.0)

    assert instance.reads == 2


def test_a_backed_off_sensor_reports_nothing_rather_than_a_stale_reading() -> None:
    """The all-null payload is what lets Home Assistant say *unavailable*.

    Serving the cache here would keep resetting `expire_after` and leave a dead
    sensor reading `unknown` forever instead.
    """
    instance = _CountingSensor()
    sensor = _sensor(_definition(entities=(('t', 'temperature'),)), instance)

    drivers.poll_entities(sensor, now=0.0)
    instance.fails = True
    drivers.poll_entities(sensor, now=1.0)
    during_backoff = drivers.poll_entities(sensor, now=1.1)

    assert during_backoff == {'t': None}
