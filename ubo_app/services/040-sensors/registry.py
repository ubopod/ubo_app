"""Sensor definition registry.

A definition describes how to recognize an I²C sensor on the bus, how to
instantiate its Adafruit driver, and which entities it exposes to Home
Assistant. Definitions are data, not code — the driver module named by a
definition still has to be on the ``DRIVER_ALLOWLIST`` in ``drivers.py``.

The registry is bundled with the image (``registry.default.json``) and only
ever loaded from there — see `load_registry` for why a downloaded one would
need more than a JSON parser.
"""

from __future__ import annotations

import json
from dataclasses import field
from pathlib import Path
from typing import Any

from immutable import Immutable

from ubo_app.logger import logger

BUNDLED_REGISTRY_PATH = Path(__file__).parent / 'registry.default.json'

Scalar = str | int | float | bool

# The 7-bit I²C address space, minus the reserved low and high ends.
MIN_I2C_ADDRESS = 0x08
MAX_I2C_ADDRESS = 0x77

# A probe reads a chip-ID register: a couple of bytes, never more.
MAX_PROBE_LENGTH = 4


class ProbeSpec(Immutable):
    """A register read that confirms a candidate definition.

    Two definitions can share an address (BME280 and BMP280 both answer on
    ``0x76``); reading a chip-ID register tells them apart.
    """

    register: int
    expected: int
    register_length: int = 1
    read_length: int = 1
    mask: int = 0xFF


class EntityDefinition(Immutable):
    """One Home Assistant entity, read from one driver attribute."""

    key: str
    attribute: str
    name: str
    # Overrides the default `{{ value_json.<key> }}`. For a reading that is a
    # code rather than a measurement — the ENS160's data-validity state — this
    # is what turns a bare `2` into "starting up" on the Home Assistant side.
    value_template: str | None = None
    device_class: str | None = None
    unit_of_measurement: str | None = None
    state_class: str | None = None
    suggested_display_precision: int | None = None


class DriverSpec(Immutable):
    """How to construct the Adafruit driver for a sensor.

    Five escape hatches, because Adafruit's drivers are not uniform:
    ``init_kwargs`` go to the constructor; ``post_init`` attributes are assigned
    on the instance afterwards (the VEML7700's integration time is a settable
    property, not a constructor argument); ``post_init_calls`` names no-argument
    methods to invoke (the VL53L1X reports nothing until ``start_ranging()``);
    ``read_method`` names a method returning *all* the sensor's values as a
    mapping (the PMSA003I's ``read()``), in which case each entity's
    ``attribute`` is a key into that mapping instead of a property name;
    ``read_primer`` names an attribute touched once before each poll to latch a
    fresh sample (the ENS160 only presents data after its ``new_data_available``
    status flag is read).
    """

    module: str
    class_name: str
    init_kwargs: dict[str, Scalar] = field(default_factory=dict)
    post_init: dict[str, Scalar] = field(default_factory=dict)
    post_init_calls: tuple[str, ...] = ()
    read_method: str | None = None
    read_primer: str | None = None


class SensorDefinition(Immutable):
    """A recognizable I²C sensor and the entities it publishes."""

    id: str
    label: str
    manufacturer: str
    addresses: tuple[int, ...]
    driver: DriverSpec
    entities: tuple[EntityDefinition, ...]
    probe: ProbeSpec | None = None
    # Seconds a sensor needs between measurements, when that is slower than the
    # poll loop. The SCD-40 produces a sample every five seconds, and each of
    # its entities is a property whose getter checks `data_ready` over the bus,
    # so polling it at 1 Hz spends fifteen round trips per sample it can
    # actually deliver. Zero — the default — means "read it every tick", which
    # is what a sensor at or above the poll rate wants.
    min_read_interval: float = 0.0


class RegistryError(Exception):
    """The registry document is structurally unusable."""


def _parse_address(value: object) -> int:
    if not isinstance(value, str):
        msg = f'address must be a hex string, got {value!r}'
        raise RegistryError(msg)
    try:
        address = int(value, 16)
    except ValueError as exception:
        # A `RegistryError` is per-definition; a bare `ValueError` would abort
        # the whole registry load and cost the user every other sensor.
        msg = f'invalid address {value!r}'
        raise RegistryError(msg) from exception
    if not MIN_I2C_ADDRESS <= address <= MAX_I2C_ADDRESS:
        msg = f'address {value} is outside the 7-bit I²C range 0x08-0x77'
        raise RegistryError(msg)
    return address


def _parse_scalars(raw: object, *, what: str) -> dict[str, Scalar]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        msg = f'{what} must be an object'
        raise RegistryError(msg)
    result: dict[str, Scalar] = {}
    for key, value in raw.items():
        # Anything richer than a scalar would let a registry document smuggle
        # structure into a driver constructor.
        if not isinstance(value, str | int | float | bool):
            msg = f'{what}.{key} must be a scalar, got {type(value).__name__}'
            raise RegistryError(msg)
        result[key] = value
    return result


def _parse_calls(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or any(not isinstance(name, str) for name in raw):
        msg = 'post_init_calls must be a list of method names'
        raise RegistryError(msg)
    return tuple(raw)


def _parse_optional_string(raw: object, *, what: str) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        msg = f'{what} must be a string, got {type(raw).__name__}'
        raise RegistryError(msg)
    return raw


def _parse_optional_precision(raw: object) -> int | None:
    if raw is None:
        return None
    # The menu renders with `f'{value:.{precision}f}'`, which raises on a
    # negative — inside an autorun selector, which redux does not swallow, so a
    # bad value here would take the whole dispatch loop down.
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        msg = f'suggested_display_precision must be a non-negative int, got {raw!r}'
        raise RegistryError(msg)
    return raw


def _parse_min_read_interval(raw: object) -> float:
    if raw is None:
        return 0.0
    # A negative interval would leave `next_read_at` permanently in the past —
    # harmless-looking, and indistinguishable from the default at a glance.
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw < 0:
        msg = f'min_read_interval must be a non-negative number, got {raw!r}'
        raise RegistryError(msg)
    return float(raw)


def _parse_probe_value(value: object, *, what: str) -> int:
    """Parse a probe register/expected/mask, written in hex like addresses.

    Datasheets quote chip-ID registers and values in hex; requiring the same
    here keeps `"register": "0xd0"` from ever being confused with a decimal.
    """
    if not isinstance(value, str):
        msg = f'probe {what} must be a hex string, got {value!r}'
        raise RegistryError(msg)
    try:
        return int(value, 16)
    except ValueError as exception:
        msg = f'invalid probe {what} {value!r}'
        raise RegistryError(msg) from exception


def _parse_probe(raw: object) -> ProbeSpec | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        msg = 'probe must be an object or null'
        raise RegistryError(msg)
    try:
        register_length = int(raw.get('register_length', 1))
        read_length = int(raw.get('read_length', 1))
        register = _parse_probe_value(raw['register'], what='register')
        expected = _parse_probe_value(raw['expected'], what='expected')
    except (KeyError, TypeError, ValueError) as exception:
        msg = f'invalid probe: {exception}'
        raise RegistryError(msg) from exception
    mask_raw = raw.get('mask')
    mask = 0xFF if mask_raw is None else _parse_probe_value(mask_raw, what='mask')

    # A probe is a chip-ID read: a couple of bytes each way. Unbounded lengths
    # are not just wrong, they are a `bytearray(read_length)` allocation and a
    # `to_bytes` that raises mid-scan — and one bad definition aborting the scan
    # costs the user every external sensor.
    for name, length in (
        ('register_length', register_length),
        ('read_length', read_length),
    ):
        if not 1 <= length <= MAX_PROBE_LENGTH:
            msg = f'{name} must be between 1 and {MAX_PROBE_LENGTH}, got {length}'
            raise RegistryError(msg)

    # Each value has to fit the width it will be written to or compared against,
    # or `int.to_bytes` raises when the probe actually runs.
    for name, value, length in (
        ('register', register, register_length),
        ('expected', expected, read_length),
        ('mask', mask, read_length),
    ):
        if not 0 <= value < 1 << (8 * length):
            msg = f'{name} {value:#x} does not fit {length} byte(s)'
            raise RegistryError(msg)

    # A bit expected outside the mask can never compare equal, so the probe
    # would silently reject every chip — the definition could never match.
    if expected & mask != expected:
        msg = f'expected {expected:#x} has bits outside mask {mask:#x}'
        raise RegistryError(msg)

    return ProbeSpec(
        register=register,
        expected=expected,
        register_length=register_length,
        read_length=read_length,
        mask=mask,
    )


def _parse_entity(raw: object) -> EntityDefinition:
    if not isinstance(raw, dict):
        msg = 'entity must be an object'
        raise RegistryError(msg)
    # `key` is interpolated straight into a Home Assistant value template
    # (`{{ value_json.<key> }}`) and used as a JSON object key on the wire, so
    # it has to be a plain identifier rather than anything template-shaped.
    key = raw.get('key')
    if not isinstance(key, str) or not key.isidentifier():
        msg = f'entity key must be an identifier, got {key!r}'
        raise RegistryError(msg)
    try:
        return EntityDefinition(
            key=key,
            attribute=str(raw['attribute']),
            name=str(raw['name']),
            value_template=_parse_optional_string(
                raw.get('value_template'),
                what='value_template',
            ),
            device_class=_parse_optional_string(
                raw.get('device_class'),
                what='device_class',
            ),
            unit_of_measurement=_parse_optional_string(
                raw.get('unit_of_measurement'),
                what='unit_of_measurement',
            ),
            state_class=_parse_optional_string(
                raw.get('state_class'),
                what='state_class',
            ),
            suggested_display_precision=_parse_optional_precision(
                raw.get('suggested_display_precision'),
            ),
        )
    except KeyError as exception:
        msg = f'entity is missing {exception}'
        raise RegistryError(msg) from exception


def _parse_definition(raw: object) -> SensorDefinition:
    if not isinstance(raw, dict):
        msg = 'definition must be an object'
        raise RegistryError(msg)

    try:
        driver_raw = raw['driver']
        if not isinstance(driver_raw, dict):
            msg = 'driver must be an object'
            raise RegistryError(msg)

        addresses = raw['addresses']
        if not isinstance(addresses, list) or not addresses:
            msg = 'addresses must be a non-empty list'
            raise RegistryError(msg)

        entities = raw['entities']
        if not isinstance(entities, list) or not entities:
            msg = 'entities must be a non-empty list'
            raise RegistryError(msg)

        return SensorDefinition(
            id=str(raw['id']),
            label=str(raw['label']),
            manufacturer=str(raw['manufacturer']),
            addresses=tuple(_parse_address(address) for address in addresses),
            driver=DriverSpec(
                module=str(driver_raw['module']),
                class_name=str(driver_raw['class']),
                init_kwargs=_parse_scalars(
                    driver_raw.get('init_kwargs'),
                    what='init_kwargs',
                ),
                post_init=_parse_scalars(
                    driver_raw.get('post_init'),
                    what='post_init',
                ),
                post_init_calls=_parse_calls(driver_raw.get('post_init_calls')),
                read_method=_parse_optional_string(
                    driver_raw.get('read_method'),
                    what='read_method',
                ),
                read_primer=_parse_optional_string(
                    driver_raw.get('read_primer'),
                    what='read_primer',
                ),
            ),
            entities=tuple(_parse_entity(entity) for entity in entities),
            probe=_parse_probe(raw.get('probe')),
            min_read_interval=_parse_min_read_interval(raw.get('min_read_interval')),
        )
    except KeyError as exception:
        msg = f'definition is missing {exception}'
        raise RegistryError(msg) from exception


def parse_registry(raw: Any) -> tuple[SensorDefinition, ...]:  # noqa: ANN401
    """Parse a registry document, skipping (and warning about) bad definitions.

    A single malformed definition must not cost the user every other sensor,
    so per-definition failures are logged and skipped. Only a structurally
    broken document raises.
    """
    if not isinstance(raw, dict):
        msg = 'registry must be an object'
        raise RegistryError(msg)

    sensors = raw.get('sensors')
    if not isinstance(sensors, list):
        msg = 'registry is missing a "sensors" list'
        raise RegistryError(msg)

    definitions: list[SensorDefinition] = []
    seen: set[str] = set()
    for entry in sensors:
        try:
            definition = _parse_definition(entry)
        except RegistryError as exception:
            logger.warning(
                'Sensors: skipping malformed registry definition',
                extra={'error': str(exception), 'definition': entry},
            )
            continue
        if definition.id in seen:
            logger.warning(
                'Sensors: skipping duplicate registry definition',
                extra={'definition_id': definition.id},
            )
            continue
        seen.add(definition.id)
        definitions.append(definition)

    return tuple(definitions)


def load_registry() -> tuple[SensorDefinition, ...]:
    """Load the sensor definitions shipped with the image.

    **Only** the bundled file, deliberately. A definition is called data, but it
    decides a class name, constructor arguments, attributes to set, methods to
    call, which attribute a reading comes from, and the Jinja template Home
    Assistant renders. The allowlist covers the *module*; everything after
    `getattr` is whatever the document says. That is close enough to executable
    that it may only come from the image.

    Loading a downloaded registry needs the updater it would come with — a
    signed or otherwise trusted channel, plus allowlisting exact driver
    descriptors rather than just modules. Nothing downloads one today, so the
    path was removed rather than left as unused attack surface.
    """
    try:
        raw = json.loads(BUNDLED_REGISTRY_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        logger.exception(
            'Sensors: unreadable sensor registry',
            extra={'path': str(BUNDLED_REGISTRY_PATH)},
        )
        return ()

    try:
        return parse_registry(raw)
    except RegistryError:
        logger.exception(
            'Sensors: unusable sensor registry',
            extra={'path': str(BUNDLED_REGISTRY_PATH)},
        )
        return ()
