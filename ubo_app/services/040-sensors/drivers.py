"""Driver allowlist and instantiation for registry-described sensors.

A registry definition names a driver module, but naming one is not enough to
get it imported: only modules on ``DRIVER_ALLOWLIST`` are ever loaded. A
definition that names anything else surfaces as ``UNSUPPORTED`` rather than
importing arbitrary code on the strength of a JSON document.
"""

from __future__ import annotations

import errno
import importlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_fixed

if TYPE_CHECKING:
    from adafruit_rgb_display.rgb import busio
    from registry import SensorDefinition

# Every driver here is a declared dependency of ubo-app. Adding a definition
# that needs a new driver means adding the dependency too — hence the
# "update ubo-app" wording on UNSUPPORTED devices.
DRIVER_ALLOWLIST = frozenset(
    {
        # On-board
        'adafruit_pct2075',
        'adafruit_veml7700',
        # STEMMA QT
        'adafruit_ahtx0',
        'adafruit_apds9960.apds9960',
        'adafruit_bh1750',
        'adafruit_bme280.basic',
        'adafruit_bme680',
        'adafruit_bmp3xx',
        'adafruit_ens160',
        'adafruit_mcp9808',
        'adafruit_pm25.i2c',
        'adafruit_scd4x',
        'adafruit_sgp40',
        'adafruit_sht4x',
        'adafruit_vl53l1x',
    },
)


class UnsupportedDriverError(Exception):
    """The definition names a driver this build cannot load."""

    def __init__(self, module: str) -> None:
        """Record the offending module so the menu can name it."""
        super().__init__(f'driver module {module!r} is not on the allowlist')
        self.module = module


@dataclass
class ActiveSensor:
    """A live driver instance and the definition it was built from.

    Driver instances are not serializable and never enter the store; the store
    holds only the ``SensorDeviceState`` describing them. The poll bookkeeping
    below is the same kind of thing — it decides when to touch the bus, and no
    consumer of the store ever sees it.
    """

    device_id: str
    definition: SensorDefinition
    instance: Any
    # Monotonic deadline before which this sensor must not be touched, set by
    # either its declared measurement interval or its failure backoff.
    next_read_at: float = 0.0
    consecutive_failures: int = 0
    last_readings: dict[str, float | None] = field(default_factory=dict)


ACTIVE_SENSORS: dict[str, ActiveSensor] = {}


def load_driver(module: str, class_name: str) -> type:
    """Import an allowlisted driver class."""
    if module not in DRIVER_ALLOWLIST:
        raise UnsupportedDriverError(module)
    imported = importlib.import_module(module)
    try:
        return getattr(imported, class_name)
    except AttributeError as exception:
        raise UnsupportedDriverError(module) from exception


@retry(
    stop=stop_after_attempt(5),
    wait=wait_fixed(1),
    retry=retry_if_exception(
        lambda e: isinstance(e, OSError) and e.errno == errno.EIO,
    ),
)
def initialize_device(
    definition: SensorDefinition,
    address: int,
    i2c: busio.I2C,
) -> Any:  # noqa: ANN401
    """Instantiate a sensor's driver, retrying through transient bus errors."""
    driver_class = load_driver(definition.driver.module, definition.driver.class_name)
    # The address goes in by keyword, never positionally: every driver that
    # takes one names the parameter `address`, but they do not agree on its
    # *position* — PM25_I2C takes `reset_pin` second, so a positional address
    # would silently become a reset pin. A sensor whose address is fixed in
    # silicon has no such parameter at all — the APDS-9960 is hard-wired to
    # `0x39` — and handing one to its constructor is a `TypeError`.
    address_kwargs = {'address': address} if definition.driver.takes_address else {}
    instance = driver_class(i2c, **address_kwargs, **definition.driver.init_kwargs)
    for attribute, value in definition.driver.post_init.items():
        setattr(instance, attribute, value)
    for method_name in definition.driver.post_init_calls:
        getattr(instance, method_name)()
    return instance


# A driver read can fail in any of these ways: a bus error (`OSError`), a sensor
# that reports "no data yet" as `None` (`TypeError` from `float(None)`), a
# corrupt frame (`RuntimeError` — how the PM25 driver reports a bad checksum),
# or a channel a driver version reports fewer of than the definition expects
# (`IndexError`).
_READ_ERRORS = (
    OSError,
    AttributeError,
    IndexError,
    KeyError,
    TypeError,
    ValueError,
    RuntimeError,
)


def _select(value: Any, index: int | None) -> float:  # noqa: ANN401
    """Narrow a driver reading to the single number one entity publishes.

    An attribute that reports several channels at once — the APDS-9960's
    ``color_data`` is one tuple of red, green, blue and clear — gives each of its
    entities the same attribute and a different ``index``.
    """
    if index is not None:
        value = value[index]
    return float(value)


def _read_attribute(
    instance: Any,  # noqa: ANN401
    attribute: str,
    index: int | None = None,
) -> float:
    """Read one value off a driver instance.

    Usually a property. Sometimes a no-argument method — the SGP40's VOC index
    comes from ``measure_index()``, not an attribute — so a callable is invoked
    rather than being handed to ``float()``, which would raise.
    """
    value: Any = getattr(instance, attribute)
    if callable(value):
        value = value()
    return _select(value, index)


def read_entities(sensor: ActiveSensor) -> dict[str, float | None]:
    """Read every entity off a live driver instance.

    Most drivers expose one property (or method) per entity. Some — the
    PMSA003I — instead return every value at once from a single `read()` call,
    which must not be made once per entity: each call consumes a fresh frame
    from the sensor. `read_method` selects that shape, and an entity's
    `attribute` is then a key into the returned mapping rather than a property
    name.

    A single unreadable entity yields ``None`` rather than losing the whole
    device's reading — a sensor that browns out on one register usually still
    answers on the others.
    """
    definition = sensor.definition
    readings: dict[str, float | None] = {}

    if definition.driver.read_primer:
        # Latch a fresh sample before reading. The ENS160 presents data only
        # once its `new_data_available` status flag has been read; without this
        # touch its data registers stay zero. Touching it is enough — the value
        # is discarded, and a failure just means this poll has no fresh sample.
        try:
            primer = getattr(sensor.instance, definition.driver.read_primer)
            if callable(primer):
                primer()
        except _READ_ERRORS:
            pass

    if definition.driver.read_method:
        try:
            data = getattr(sensor.instance, definition.driver.read_method)()
        except _READ_ERRORS:
            return {entity.key: None for entity in definition.entities}

        for entity in definition.entities:
            try:
                readings[entity.key] = (
                    _select(data[entity.attribute], entity.index)
                    if entity.attribute in data
                    # Not everything such a driver exposes is *in* the mapping:
                    # the ENS160 buffers its measurements there, but reports
                    # data validity from a live status register.
                    else _read_attribute(
                        sensor.instance,
                        entity.attribute,
                        entity.index,
                    )
                )
            except _READ_ERRORS:
                readings[entity.key] = None
        return readings

    for entity in definition.entities:
        try:
            readings[entity.key] = _read_attribute(
                sensor.instance,
                entity.attribute,
                entity.index,
            )
        except _READ_ERRORS:
            readings[entity.key] = None
    return readings


# A device whose *every* entity failed is not momentarily busy — on this bus it
# usually means a slave is wedged holding SDA low, which takes every other
# device down with it and outlives a poll tick by minutes. Retrying at 1 Hz
# through that adds two aborted transactions a second to a bus already in
# trouble, so each consecutive failure doubles the wait.
BACKOFF_INITIAL_SECONDS = 2.0
BACKOFF_MAX_SECONDS = 60.0


def poll_entities(sensor: ActiveSensor, *, now: float) -> dict[str, float | None]:
    """Read a sensor's entities if it is due, honoring its interval and backoff.

    `now` is a monotonic timestamp taken once per poll tick by the caller, so
    every sensor in a tick is judged against the same clock reading.
    """
    if now < sensor.next_read_at:
        if sensor.consecutive_failures:
            # A sensor that is failing has nothing to say, and saying so is
            # what lets Home Assistant mark it unavailable. Replaying the cache
            # here would keep resetting `expire_after` and leave a dead sensor
            # reading `unknown` forever instead.
            return dict.fromkeys(
                entity.key for entity in sensor.definition.entities
            )
        # Inside its measurement interval a sensor is merely quiet. Its last
        # sample is still the current one — the drivers themselves return
        # exactly that between measurements — so the cache is not a stale
        # reading, it is the same reading without the round trip.
        return dict(sensor.last_readings)

    readings = read_entities(sensor)

    if all(value is None for value in readings.values()):
        sensor.consecutive_failures += 1
        delay = min(
            BACKOFF_INITIAL_SECONDS * 2 ** (sensor.consecutive_failures - 1),
            BACKOFF_MAX_SECONDS,
        )
    else:
        sensor.consecutive_failures = 0
        sensor.last_readings = readings
        delay = sensor.definition.min_read_interval

    sensor.next_read_at = now + delay
    return readings
