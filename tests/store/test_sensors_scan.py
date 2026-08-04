"""Tests for I²C scan matching.

``match_definitions`` is the pure half of scanning, so it is tested with a
fake probe runner that records which addresses it was asked about. The
recording matters as much as the matching: probing an address *writes* a
register pointer to it, and the on-board audio codec must never be written to.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Sequence


from tests.service_loader import load_service_modules

registry, scan = load_service_modules(
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '040-sensors',
    'registry',
    'scan',
)


class _ProbeRecorder:
    """A probe runner that records every address it is asked to poke."""

    def __init__(self, answers: dict[tuple[int, int], bool] | None = None) -> None:
        self.answers = answers or {}
        self.probed: list[int] = []

    def __call__(self, address: int, probe: Any) -> bool:  # noqa: ANN401
        self.probed.append(address)
        return self.answers.get((address, probe.expected), False)


def _definition(
    definition_id: str,
    addresses: Sequence[int],
    *,
    expected: int | None = None,
) -> Any:  # noqa: ANN401
    return registry.SensorDefinition(
        id=definition_id,
        label=definition_id.upper(),
        manufacturer='ACME',
        addresses=tuple(addresses),
        driver=registry.DriverSpec(module=f'adafruit_{definition_id}', class_name='X'),
        entities=(
            registry.EntityDefinition(
                key='temperature',
                attribute='temperature',
                name='Temperature',
            ),
        ),
        probe=None
        if expected is None
        else registry.ProbeSpec(register=0xD0, expected=expected),
    )


def test_reserved_addresses_are_never_matched_or_probed() -> None:
    """The codec, the EEPROM and the keypad expander are untouchable.

    A probe writes before it reads, so poking the WM8960 could change audio
    configuration. Even a definition that claims a reserved address must not
    cause it to be probed.
    """
    greedy = _definition('greedy', sorted(scan.RESERVED_ADDRESSES), expected=0x60)
    probe_runner = _ProbeRecorder()

    matches = scan.match_definitions(
        scan.RESERVED_ADDRESSES,
        [greedy],
        probe_runner,
    )

    assert matches == ()
    assert probe_runner.probed == []


def test_skip_addresses_are_not_matched() -> None:
    """Built-in addresses come from the EEPROM and are excluded from the scan.

    Otherwise the on-board PCT2075 would be listed twice: once as a built-in
    and once as a freshly-discovered device.
    """
    pct2075 = _definition('pct2075', [0x48])
    probe_runner = _ProbeRecorder()

    matches = scan.match_definitions(
        [0x48],
        [pct2075],
        probe_runner,
        skip_addresses=frozenset({0x48}),
    )

    assert matches == ()
    assert probe_runner.probed == []


def test_a_lone_probe_less_candidate_wins() -> None:
    """One probe-less definition claiming an address is an unambiguous match."""
    aht20 = _definition('aht20', [0x38])

    (match,) = scan.match_definitions([0x38], [aht20], _ProbeRecorder())

    assert match.address == 0x38
    assert match.definition is aht20
    assert match.is_builtin is False


def test_a_probe_disambiguates_a_shared_address() -> None:
    """BME280 and BMP280 both answer on 0x76; the chip-ID register decides."""
    bme280 = _definition('bme280', [0x76, 0x77], expected=0x60)
    bmp280 = _definition('bmp280', [0x76, 0x77], expected=0x58)
    probe_runner = _ProbeRecorder(answers={(0x76, 0x60): True})

    (match,) = scan.match_definitions([0x76], [bme280, bmp280], probe_runner)

    assert match.definition is bme280
    assert probe_runner.probed == [0x76, 0x76]


def test_a_probe_hit_beats_a_probe_less_candidate() -> None:
    """A definition that positively identifies itself outranks a guess."""
    bme280 = _definition('bme280', [0x76], expected=0x60)
    guess = _definition('guess', [0x76])
    probe_runner = _ProbeRecorder(answers={(0x76, 0x60): True})

    (match,) = scan.match_definitions([0x76], [bme280, guess], probe_runner)

    assert match.definition is bme280


def test_colliding_probe_less_candidates_are_ambiguous() -> None:
    """Two probe-less definitions on one address: surface it, don't guess."""
    first = _definition('first', [0x38])
    second = _definition('second', [0x38])

    (match,) = scan.match_definitions([0x38], [first, second], _ProbeRecorder())

    assert match.address == 0x38
    assert match.definition is None


def test_an_address_whose_probes_all_miss_is_ignored() -> None:
    """Some other chip lives there — not our business, and not an error."""
    bme280 = _definition('bme280', [0x76], expected=0x60)

    matches = scan.match_definitions([0x76], [bme280], _ProbeRecorder())

    assert matches == ()


def test_unclaimed_addresses_are_ignored() -> None:
    """An address no definition claims is never probed."""
    aht20 = _definition('aht20', [0x38])
    probe_runner = _ProbeRecorder()

    matches = scan.match_definitions([0x62], [aht20], probe_runner)

    assert matches == ()
    assert probe_runner.probed == []


class _Chip:
    """A fake chip: answers register reads from its own map, 0x00 elsewhere.

    Standing in for a real device lets us drive `match_definitions` with the
    *shipped* registry and assert it identifies the right sensor.
    """

    def __init__(self, registers: dict[int, int]) -> None:
        self.registers = registers

    def __call__(self, address: int, probe: Any) -> bool:  # noqa: ANN401, ARG002
        return self.registers.get(probe.register, 0x00) & probe.mask == probe.expected


# Bosch parts that all answer on 0x76/0x77 and are told apart only by a chip-ID
# read — and not even at the same register: the BMP3xx keeps its ID at 0x00,
# the BME2xx/BME6xx at 0xd0.
_BME280_CHIP = _Chip({0xD0: 0x60})
_BME680_CHIP = _Chip({0xD0: 0x61})
_BMP388_CHIP = _Chip({0x00: 0x50})


@pytest.mark.parametrize(
    ('chip', 'expected_id'),
    [
        (_BME280_CHIP, 'bme280'),
        (_BME680_CHIP, 'bme680'),
        (_BMP388_CHIP, 'bmp388'),
    ],
)
@pytest.mark.parametrize('address', [0x76, 0x77])
def test_the_bosch_pileup_on_0x76_is_resolved_by_probes(
    chip: _Chip,
    expected_id: str,
    address: int,
) -> None:
    """BME280, BME680 and BMP388 all claim 0x76/0x77 — exactly one may win.

    This is the case the whole probe mechanism exists for. A second match would
    mean AMBIGUOUS (no sensor at all for the user); a wrong single match would
    mean the wrong driver, silently reporting wrong numbers.
    """
    definitions = registry.load_registry()

    matches = scan.match_definitions([address], definitions, chip)

    assert len(matches) == 1
    assert matches[0].definition is not None
    assert matches[0].definition.id == expected_id
    assert matches[0].address == address


def test_an_unknown_bosch_part_matches_nothing_rather_than_guessing() -> None:
    """A BMP390 (chip id 0x60 at register 0x00) is not in the registry.

    It must not be mistaken for the BME280, whose ID is also 0x60 — but at a
    different register.
    """
    definitions = registry.load_registry()
    bmp390 = _Chip({0x00: 0x60})

    assert scan.match_definitions([0x77], definitions, bmp390) == ()


def test_device_ids_are_stable_across_scans() -> None:
    """The id encodes definition and address, so it survives a re-scan."""
    assert scan.make_device_id('bme280', 0x76) == 'bme280_0x76'
    assert scan.make_device_id('', 0x76) == 'unknown_0x76'


class _QuickWriteRecorder:
    """A quick-write probe that records every address it is asked to poke."""

    def __init__(self, present: set[int] | None = None) -> None:
        self.present = present or set()
        self.probed: list[int] = []

    def __call__(self, address: int) -> bool:
        self.probed.append(address)
        return address in self.present


def test_quick_write_recovers_a_sensor_the_read_scan_missed() -> None:
    """SCD4x (0x62) NAKs the read scan but ACKs an address-only write.

    Without the supplement it is invisible; with it, the address joins the set.
    """
    scd4x = _definition('scd4x', [0x62])
    probe = _QuickWriteRecorder(present={0x62})

    found = scan.discovered_addresses([0x12], [scd4x], probe)

    assert 0x62 in found
    assert 0x12 in found  # the read scan's own hits are kept


def test_quick_write_only_probes_claimed_addresses() -> None:
    """The supplement pokes exactly the registry's addresses — nothing else.

    Probing an unclaimed address would be writing to a chip we have no
    definition for; some EEPROMs corrupt on a stray write.
    """
    scd4x = _definition('scd4x', [0x62])
    probe = _QuickWriteRecorder()

    scan.discovered_addresses([], [scd4x], probe)

    assert probe.probed == [0x62]


def test_quick_write_skips_addresses_the_read_scan_already_found() -> None:
    """No point re-probing an address the cheap read scan already saw."""
    sgp40 = _definition('sgp40', [0x59])
    probe = _QuickWriteRecorder(present={0x59})

    found = scan.discovered_addresses([0x59], [sgp40], probe)

    assert probe.probed == []
    assert 0x59 in found


def test_quick_write_never_probes_reserved_or_skipped_addresses() -> None:
    """Address-only writes are safe, but reserved/built-in addresses stay off-limits."""
    greedy = _definition('greedy', [*sorted(scan.RESERVED_ADDRESSES), 0x48])
    probe = _QuickWriteRecorder(present=set(scan.RESERVED_ADDRESSES) | {0x48})

    scan.discovered_addresses(
        [],
        [greedy],
        probe,
        skip_addresses=frozenset({0x48}),
    )

    assert probe.probed == []


def test_shipped_registry_recovers_scd4x_and_sgp40_from_quick_write() -> None:
    """End to end: the read scan sees only the PMSA003I; quick-write finds the rest.

    This is the exact on-device situation — SCD41 at 0x62 and SGP40 at 0x59 are
    both write-only-addressable and missed by `i2c.scan()`.
    """
    definitions = registry.load_registry()
    probe = _QuickWriteRecorder(present={0x59, 0x62})

    found = scan.discovered_addresses([0x12], definitions, probe)
    matches = scan.match_definitions(found, definitions, _ProbeRecorder())

    matched_ids = {
        match.definition.id for match in matches if match.definition is not None
    }
    assert {'scd4x', 'sgp40', 'pmsa003i'} <= matched_ids


@pytest.mark.parametrize(
    ('entry', 'why'),
    [
        pytest.param('pct2075', 'the entry is not a mapping', id='not-a-mapping'),
        pytest.param(
            {'model': 'pct2075', 'bus_address': 'zz'},
            'the address is not hex',
            id='unreadable-address',
        ),
        pytest.param(
            {'model': 'pct2075', 'bus_address': 0x48},
            'the address is not a string',
            id='non-string-address',
        ),
        pytest.param(
            {'model': 'pct2075', 'bus_address': '0x1a'},
            'the WM8960 audio codec',
            id='reserved-address',
        ),
        pytest.param(
            {'model': 'pct2075', 'bus_address': '0x05'},
            'outside the 7-bit range',
            id='out-of-range',
        ),
        pytest.param(
            {'model': 'pct2075', 'bus_address': '0x76'},
            'an address pct2075 does not claim',
            id='not-claimed',
        ),
    ],
)
def test_a_bad_eeprom_entry_is_refused(
    entry: object,
    why: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The EEPROM is on-board, but it is still data.

    A built-in skips the scan entirely, so its address goes straight to a driver
    constructor — this is the only place the scanner's hardware-safety rules can
    be applied to it.
    """
    _ = why
    monkeypatch.setattr(scan, 'get_eeprom_data', lambda: {'temperature': entry})

    assert scan.builtin_matches(registry.load_registry()) == ()


def test_a_good_eeprom_entry_is_still_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard must not throw away the on-board sensors it exists to find."""
    monkeypatch.setattr(
        scan,
        'get_eeprom_data',
        lambda: {'temperature': {'model': 'PCT2075', 'bus_address': '0x48'}},
    )

    ((match, sensor),) = scan.builtin_matches(registry.load_registry())

    assert match.address == 0x48
    assert match.is_builtin is True
    assert match.definition is not None
    assert match.definition.id == 'pct2075'
    assert sensor is scan.Sensor.TEMPERATURE
