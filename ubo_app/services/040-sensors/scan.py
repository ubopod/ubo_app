"""I²C bus scanning and registry matching.

Scanning is split in two so the interesting half can be tested without a bus:
``match_definitions`` is pure and takes a ``probe_runner`` callback, while
``scan_and_match`` supplies a real one and owns the bus lock.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Protocol

from immutable import Immutable
from registry import MAX_I2C_ADDRESS, MIN_I2C_ADDRESS

from ubo_app.logger import logger
from ubo_app.store.services.sensors import Sensor
from ubo_app.utils import IS_RPI
from ubo_app.utils.eeprom import get_eeprom_data

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from adafruit_rgb_display.rgb import busio
    from registry import ProbeSpec, SensorDefinition

# Addresses owned by on-board peripherals. These are never probed: a probe
# *writes* a register pointer before reading, and a stray byte to the WM8960
# codec is a partial register write that can change audio configuration. The
# EEPROM and the keypad expander are excluded for the same reason — we have no
# business poking hardware whose identity we already know.
RESERVED_ADDRESSES = frozenset(
    {
        0x1A,  # WM8960 audio codec
        0x50,  # HAT EEPROM
        0x58,  # AW9523 keypad GPIO expander (000-keypad/setup.py)
    },
)

# The bus is a Blinka singleton shared with 000-keypad, so the lock is
# contended. Bail out rather than block the service forever.
_LOCK_TIMEOUT = 2.0
_LOCK_POLL_INTERVAL = 0.01


class ProbeRunner(Protocol):
    """Reads a sensor's ID register and says whether it matches the probe."""

    def __call__(self, address: int, probe: ProbeSpec) -> bool:
        """Return whether the device at ``address`` answers the probe."""
        ...


class QuickWriteProbe(Protocol):
    """Address-only write probe: says whether an address ACKs, writing no data."""

    def __call__(self, address: int) -> bool:
        """Return whether the device at ``address`` ACKs an address-only write."""
        ...


class SensorMatch(Immutable):
    """One address on the bus, resolved (or not) to a definition.

    ``definition is None`` means two probe-less definitions claim the address
    and nothing distinguishes them — the device is surfaced as unrecognized
    rather than guessed at.
    """

    address: int
    definition: SensorDefinition | None = None
    is_builtin: bool = False


class BusLockTimeoutError(Exception):
    """The I²C bus stayed locked by another service."""


def make_device_id(definition_id: str, address: int) -> str:
    """Build the stable id for a device: definition plus where it lives."""
    return f'{definition_id or "unknown"}_{address:#04x}'


def match_definitions(
    addresses: Iterable[int],
    definitions: Sequence[SensorDefinition],
    probe_runner: ProbeRunner,
    skip_addresses: frozenset[int] = frozenset(),
) -> tuple[SensorMatch, ...]:
    """Resolve scanned addresses against the registry.

    Precedence at a given address: a definition whose probe answers wins; if
    none has a probe, a lone probe-less candidate wins; anything else is
    ambiguous. Addresses nothing claims are ignored — an unknown chip on the
    bus is not our business.
    """
    matches: list[SensorMatch] = []

    for address in sorted(set(addresses)):
        if address in RESERVED_ADDRESSES or address in skip_addresses:
            continue

        candidates = [
            definition
            for definition in definitions
            if address in definition.addresses
        ]
        if not candidates:
            continue

        probed = [
            definition
            for definition in candidates
            if definition.probe is not None
            and probe_runner(address, definition.probe)
        ]
        if len(probed) == 1:
            matches.append(SensorMatch(address=address, definition=probed[0]))
            continue
        if len(probed) > 1:
            logger.warning(
                'Sensors: multiple probes matched one address',
                extra={
                    'address': hex(address),
                    'candidates': [definition.id for definition in probed],
                },
            )
            matches.append(SensorMatch(address=address))
            continue

        probe_less = [
            definition for definition in candidates if definition.probe is None
        ]
        if len(probe_less) == 1:
            matches.append(SensorMatch(address=address, definition=probe_less[0]))
            continue
        if len(probe_less) > 1:
            logger.warning(
                'Sensors: address is claimed by several probe-less definitions',
                extra={
                    'address': hex(address),
                    'candidates': [definition.id for definition in probe_less],
                },
            )
            matches.append(SensorMatch(address=address))
            continue

        # Every candidate carried a probe and none answered — some other chip
        # lives here.
        logger.debug(
            'Sensors: no definition claimed a scanned address',
            extra={'address': hex(address)},
        )

    return tuple(matches)


def _eeprom_address(
    raw: object,
    definition: SensorDefinition,
) -> int | None:
    """Read an on-board sensor's address off the EEPROM, or None if unusable.

    The EEPROM is on-board data, but it is still *data*: a corrupt or
    mis-programmed HAT would otherwise crash start-up, or — worse — hand an
    address straight to a driver constructor. Built-ins skip the scan entirely,
    so this is the only place that check can happen, and it has to be as strict
    as the scanner: in range, claimed by the definition, and never a reserved
    address that belongs to the codec, the EEPROM or the keypad expander.
    """
    if not isinstance(raw, str):
        return None
    try:
        address = int(raw, 16)
    except ValueError:
        logger.warning(
            'Sensors: EEPROM holds an unreadable bus address',
            extra={'model': definition.id, 'bus_address': raw},
        )
        return None
    if (
        not MIN_I2C_ADDRESS <= address <= MAX_I2C_ADDRESS
        or address in RESERVED_ADDRESSES
        or address not in definition.addresses
    ):
        logger.warning(
            'Sensors: refusing an unsafe EEPROM bus address',
            extra={'model': definition.id, 'address': hex(address)},
        )
        return None
    return address


def builtin_matches(
    definitions: Sequence[SensorDefinition],
) -> tuple[tuple[SensorMatch, Sensor], ...]:
    """Resolve the on-board sensors from the EEPROM, not from the bus.

    Their model and address are recorded in the HAT EEPROM, so they need no
    scanning and no probing. Each is paired with the legacy ``Sensor`` slot it
    feeds, which is what keeps the status bar working.
    """
    eeprom_data = get_eeprom_data()
    by_id = {definition.id: definition for definition in definitions}
    result: list[tuple[SensorMatch, Sensor]] = []

    for entry, legacy_sensor in (
        (eeprom_data.get('temperature'), Sensor.TEMPERATURE),
        (eeprom_data.get('ambient'), Sensor.LIGHT),
    ):
        if not isinstance(entry, dict):
            continue
        model = str(entry.get('model', '')).lower()
        if not model:
            continue

        definition = by_id.get(model)
        if definition is None:
            logger.warning(
                'Sensors: EEPROM names a model with no registry definition',
                extra={'model': model},
            )
            continue

        address = _eeprom_address(entry.get('bus_address'), definition)
        if address is None:
            continue

        result.append(
            (
                SensorMatch(
                    address=address,
                    definition=definition,
                    is_builtin=True,
                ),
                legacy_sensor,
            ),
        )

    return tuple(result)


def _acquire(i2c: busio.I2C) -> None:
    deadline = time.monotonic() + _LOCK_TIMEOUT
    while not i2c.try_lock():
        if time.monotonic() >= deadline:
            msg = 'timed out waiting for the I²C bus lock'
            raise BusLockTimeoutError(msg)
        time.sleep(_LOCK_POLL_INTERVAL)


def _read_probe(i2c: busio.I2C, address: int, probe: ProbeSpec) -> bool:
    """Read a device's ID register. Never called for a reserved address."""
    try:
        buffer = bytearray(probe.read_length)
        i2c.writeto_then_readfrom(
            address,
            probe.register.to_bytes(probe.register_length, 'big'),
            buffer,
        )
    except OSError:
        # Not everything answers a register read; that just means "not this
        # definition", not an error worth surfacing.
        return False
    return int.from_bytes(buffer, 'big') & probe.mask == probe.expected


def discovered_addresses(
    scanned: Iterable[int],
    definitions: Sequence[SensorDefinition],
    quick_write_probe: QuickWriteProbe,
    skip_addresses: frozenset[int] = frozenset(),
) -> frozenset[int]:
    """Widen a read-based scan with an address-only write probe.

    ``i2c.scan()`` reads a byte from every address, but some sensors NAK a bare
    read and are invisible to it — Sensirion's SCD4x (``0x62``) and SGP40
    (``0x59``) both do — while they ACK an address-only write, the same probe
    ``i2cdetect`` uses for most addresses. So supplement the read scan by
    quick-write-probing *only* the addresses the registry actually claims and
    the scan did not already find. Probing the bounded set of known sensor
    addresses — never an arbitrary or reserved one — keeps us from poking chips
    (some EEPROMs dislike a stray write) we have no definition for.
    """
    found = set(scanned)
    claimed = {
        address for definition in definitions for address in definition.addresses
    }
    for address in sorted(claimed - found):
        if address in RESERVED_ADDRESSES or address in skip_addresses:
            continue
        if quick_write_probe(address):
            found.add(address)
    return frozenset(found)


def _quick_write_probe(i2c: busio.I2C, address: int) -> bool:
    """ACK test with an address-only write: START, addr+W, STOP — no data.

    Writes no register pointer and no data byte, so it is as safe as the scan
    itself. Reaches through Blinka's Linux I²C wrapper to the SMBus object,
    degrading to "not found" if that internal shape ever changes rather than
    breaking the scan.
    """
    bus = getattr(getattr(i2c, '_i2c', None), '_i2c_bus', None)
    write_quick = getattr(bus, 'write_quick', None)
    if write_quick is None:
        return False
    try:
        write_quick(address)
    except OSError:
        return False
    return True


def scan_and_match(
    i2c: busio.I2C,
    definitions: Sequence[SensorDefinition],
    skip_addresses: frozenset[int],
) -> tuple[SensorMatch, ...]:
    """Scan the bus and resolve what's on it.

    Blocking — call it from a thread. The bus lock is taken once and held
    across the scan and every probe, so the window is a handful of register
    reads and never spans an ``await``.
    """
    if not IS_RPI:
        return ()

    _acquire(i2c)
    try:
        addresses = discovered_addresses(
            i2c.scan(),
            definitions,
            lambda address: _quick_write_probe(i2c, address),
            skip_addresses=skip_addresses,
        )
        logger.debug('Sensors: scanned the I²C bus', extra={'count': len(addresses)})
        return match_definitions(
            addresses,
            definitions,
            lambda address, probe: _read_probe(i2c, address, probe),
            skip_addresses=skip_addresses,
        )
    finally:
        i2c.unlock()
