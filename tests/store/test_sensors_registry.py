"""Tests for the sensor definition registry and the driver allowlist.

The registry is data that decides which code gets imported, so the two things
worth pinning down are: a malformed definition must not cost the user the
other definitions, and a definition must never be able to import a module the
build didn't ship.

Service modules live under ``ubo_app/services/040-sensors``, which is not an
importable package path — same ``sys.path`` loader as ``test_camera_reducer``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.service_loader import load_service_modules

registry, drivers, scan = load_service_modules(
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '040-sensors',
    'registry',
    'drivers',
    'scan',
)


def _definition(**overrides: Any) -> dict[str, Any]:  # noqa: ANN401
    base: dict[str, Any] = {
        'id': 'bme280',
        'label': 'BME280',
        'manufacturer': 'Bosch',
        'addresses': ['0x76', '0x77'],
        'probe': {'register': '0xd0', 'expected': '0x60'},
        'driver': {'module': 'adafruit_bme280.basic', 'class': 'Adafruit_BME280_I2C'},
        'entities': [
            {
                'key': 'temperature',
                'attribute': 'temperature',
                'name': 'Temperature',
                'device_class': 'temperature',
                'unit_of_measurement': '°C',
                'state_class': 'measurement',
                'suggested_display_precision': 1,
            },
        ],
    }
    base.update(overrides)
    return base


def test_parses_a_well_formed_definition() -> None:
    """Addresses are hex-decoded and the probe/entities are carried through."""
    (definition,) = registry.parse_registry({'sensors': [_definition()]})

    assert definition.id == 'bme280'
    assert definition.addresses == (0x76, 0x77)
    assert definition.probe is not None
    assert definition.probe.register == 0xD0
    assert definition.probe.expected == 0x60
    assert definition.probe.register_length == 1
    assert definition.driver.module == 'adafruit_bme280.basic'
    assert definition.driver.class_name == 'Adafruit_BME280_I2C'
    assert definition.entities[0].attribute == 'temperature'


def test_probe_may_be_absent() -> None:
    """A probe-less definition is legal — some sensors have no ID register."""
    (definition,) = registry.parse_registry(
        {'sensors': [_definition(probe=None)]},
    )

    assert definition.probe is None


@pytest.mark.parametrize(
    'override',
    [
        {'addresses': []},
        {'addresses': ['0x07']},  # below the 7-bit range
        {'addresses': ['0x78']},  # above the 7-bit range
        {'addresses': [118]},  # not a hex string
        {'entities': []},
        {'driver': {'module': 'adafruit_bme280.basic'}},  # no class
    ],
)
def test_malformed_definitions_are_skipped_not_fatal(
    override: dict[str, Any],
) -> None:
    """A bad definition is dropped; the good ones alongside it survive."""
    good = _definition(id='sht4x', addresses=['0x44'], probe=None)

    definitions = registry.parse_registry(
        {'sensors': [_definition(**override), good]},
    )

    assert [definition.id for definition in definitions] == ['sht4x']


def test_duplicate_ids_are_skipped() -> None:
    """The first definition for an id wins; later ones are dropped."""
    definitions = registry.parse_registry(
        {
            'sensors': [
                _definition(label='First'),
                _definition(label='Second'),
            ],
        },
    )

    assert [definition.label for definition in definitions] == ['First']


def test_non_scalar_init_kwargs_are_rejected() -> None:
    """A registry document cannot smuggle structure into a driver constructor."""
    definitions = registry.parse_registry(
        {
            'sensors': [
                _definition(
                    driver={
                        'module': 'adafruit_bme280.basic',
                        'class': 'Adafruit_BME280_I2C',
                        'init_kwargs': {'evil': {'nested': 'object'}},
                    },
                ),
            ],
        },
    )

    assert definitions == ()


def test_structurally_broken_registry_raises() -> None:
    """A document with no `sensors` list is unusable, not merely lossy."""
    with pytest.raises(registry.RegistryError):
        registry.parse_registry({'version': 1})


def test_bundled_registry_loads_and_describes_the_builtins() -> None:
    """The shipped registry parses, and its drivers are all allowlisted."""
    definitions = registry.load_registry()

    by_id = {definition.id: definition for definition in definitions}
    assert 'pct2075' in by_id
    assert 'veml7700' in by_id

    for definition in definitions:
        assert definition.driver.module in drivers.DRIVER_ALLOWLIST

    # The VEML7700's 50 ms integration time is a settable property, not a
    # constructor argument — the old service set it by hand and the registry
    # has to keep doing so or the light readings change.
    assert by_id['veml7700'].driver.post_init == {'light_integration_time': 8}
    assert by_id['pct2075'].entities[0].attribute == 'temperature'
    assert by_id['veml7700'].entities[0].attribute == 'lux'


def test_bundled_registry_never_claims_a_reserved_address() -> None:
    """No definition may claim an address owned by on-board hardware.

    `scan` refuses to probe the reserved addresses (a probe writes before it
    reads, and the WM8960 codec sits on 0x1a), so a definition claiming one
    could never be detected there anyway — and would be advertising a hardware
    conflict. The MCP9808 legitimately supports 0x18-0x1f; 0x1a is deliberately
    left out of its list for exactly this reason.
    """
    for definition in registry.load_registry():
        clashes = set(definition.addresses) & scan.RESERVED_ADDRESSES
        assert not clashes, (
            f'{definition.id} claims reserved address(es) '
            f'{[hex(address) for address in clashes]}'
        )


def test_bundled_registry_has_no_unresolvable_ambiguity() -> None:
    """No address may be claimed by two probe-less definitions.

    That combination is what `match_definitions` reports as AMBIGUOUS, and the
    picker UI for resolving it is deliberately not built — no sensor in the
    shipped set can trigger it. Adding a definition that *could* must fail here
    rather than stranding a user with a device they cannot identify.
    """
    claims: dict[int, list[str]] = {}
    for definition in registry.load_registry():
        if definition.probe is not None:
            continue
        for address in definition.addresses:
            claims.setdefault(address, []).append(definition.id)

    collisions = {
        hex(address): ids for address, ids in claims.items() if len(ids) > 1
    }
    assert not collisions, (
        f'probe-less definitions collide: {collisions}. Give one of them a '
        f'probe, or build the ambiguity picker.'
    )


def test_every_bundled_driver_is_importable() -> None:
    """Each definition's driver module and class must actually exist.

    The registry names drivers as strings, so a typo (`adafruit_bme280` instead
    of `adafruit_bme280.basic`) would otherwise only surface on the device, as
    an UNSUPPORTED sensor.
    """
    for definition in registry.load_registry():
        driver_class = drivers.load_driver(
            definition.driver.module,
            definition.driver.class_name,
        )
        assert driver_class.__name__ == definition.driver.class_name

        if definition.driver.read_method:
            # Values come from a mapping this method returns, so the entity
            # attributes are dict keys and cannot be checked against the class.
            assert callable(
                getattr(driver_class, definition.driver.read_method, None),
            ), (
                f'{definition.id}: {driver_class.__name__} has no '
                f'{definition.driver.read_method}() method'
            )
        else:
            # Every entity has to name an attribute the driver actually exposes.
            for entity in definition.entities:
                assert hasattr(driver_class, entity.attribute), (
                    f'{definition.id}: {driver_class.__name__} has no '
                    f'{entity.attribute!r}'
                )

        for method_name in definition.driver.post_init_calls:
            assert callable(getattr(driver_class, method_name, None)), (
                f'{definition.id}: {driver_class.__name__} has no '
                f'{method_name}() method'
            )

        # A typo here fails silently in production: `setattr` happily creates
        # the misspelled attribute and the driver stays at its defaults — the
        # VEML7700's integration time changes every lux reading it makes.
        # `dir` rather than `hasattr`: register descriptors like `RWBits`
        # raise on class-level access, which `hasattr` reads as absence.
        for attribute in definition.driver.post_init:
            assert attribute in dir(driver_class), (
                f'{definition.id}: {driver_class.__name__} has no '
                f'{attribute!r} to assign post-init'
            )


def test_every_bundled_takes_address_matches_its_driver() -> None:
    """`takes_address` must say exactly what the driver's signature says.

    `initialize_device` passes the address by keyword, so a driver that takes one
    must name it `address` — positionally it would land in the wrong parameter,
    since `PM25_I2C`'s second argument is `reset_pin`. A driver whose address is
    fixed in silicon has no such parameter, and passing one is a `TypeError`;
    that is what `takes_address: false` is for. Asserting equality rather than
    membership catches the flag being wrong in *either* direction.
    """
    import inspect

    for definition in registry.load_registry():
        driver_class = drivers.load_driver(
            definition.driver.module,
            definition.driver.class_name,
        )
        parameters = inspect.signature(driver_class.__init__).parameters
        assert definition.driver.takes_address == ('address' in parameters), (
            f'{definition.id}: takes_address is '
            f'{definition.driver.takes_address} but {driver_class.__name__}'
            f'{"" if "address" in parameters else " has no"} `address` parameter'
        )


def test_load_driver_rejects_a_module_off_the_allowlist() -> None:
    """A definition naming an unshipped driver cannot import it."""
    with pytest.raises(drivers.UnsupportedDriverError):
        drivers.load_driver('os', 'system')


def test_load_driver_imports_an_allowlisted_module() -> None:
    """An allowlisted driver resolves to its class."""
    driver_class = drivers.load_driver('adafruit_pct2075', 'PCT2075')

    assert driver_class.__name__ == 'PCT2075'


def test_an_invalid_hex_address_drops_only_its_own_definition() -> None:
    """`int(value, 16)` raises, and `parse_registry` only skips `RegistryError`.

    An unwrapped `ValueError` would abort the whole load and cost the user every
    other sensor over one bad entry.
    """
    document = {
        'sensors': [
            {
                'id': 'broken',
                'label': 'Broken',
                'manufacturer': 'X',
                'addresses': ['not-hex'],
                'driver': {'module': 'adafruit_bh1750', 'class': 'BH1750'},
                'entities': [
                    {'key': 'illuminance', 'attribute': 'lux', 'name': 'Light'},
                ],
            },
            {
                'id': 'fine',
                'label': 'Fine',
                'manufacturer': 'X',
                'addresses': ['0x23'],
                'driver': {'module': 'adafruit_bh1750', 'class': 'BH1750'},
                'entities': [
                    {'key': 'illuminance', 'attribute': 'lux', 'name': 'Light'},
                ],
            },
        ],
    }

    definitions = registry.parse_registry(document)

    assert [definition.id for definition in definitions] == ['fine']


@pytest.mark.parametrize(
    'probe',
    [
        pytest.param(
            {'register': '0x00', 'expected': '0x00', 'read_length': 0},
            id='zero',
        ),
        pytest.param(
            {'register': '0x00', 'expected': '0x00', 'read_length': -1},
            id='negative',
        ),
        pytest.param(
            {'register': '0x00', 'expected': '0x00', 'read_length': 1 << 20},
            id='enormous',
        ),
        pytest.param(
            {'register': '0x00', 'expected': '0x00', 'register_length': 0},
            id='zero-register-length',
        ),
        pytest.param(
            {'register': '0x1ff', 'expected': '0x00', 'register_length': 1},
            id='register-too-wide',
        ),
        pytest.param(
            {'register': '0x00', 'expected': '0x1ff', 'read_length': 1},
            id='expected-too-wide',
        ),
        pytest.param(
            {'register': '0x00', 'expected': '0x00', 'mask': '0x1ff', 'read_length': 1},
            id='mask-too-wide',
        ),
        pytest.param(
            {'register': 208, 'expected': '0x60'},
            id='decimal-register',
        ),
        pytest.param(
            {'register': '0xd0', 'expected': 96},
            id='decimal-expected',
        ),
        pytest.param(
            {'register': '0xd0', 'expected': '0x60', 'mask': 255},
            id='decimal-mask',
        ),
        pytest.param(
            {'register': '0xd0', 'expected': 'not-hex'},
            id='unparsable-hex',
        ),
        pytest.param(
            {'register': '0x00', 'expected': '0x02', 'mask': '0x01'},
            id='expected-outside-mask',
        ),
    ],
)
def test_an_unusable_probe_drops_only_its_own_definition(probe: dict) -> None:
    """An unbounded length allocates, and a too-wide value raises mid-scan.

    Probe registers, expected values and masks are hex strings — like
    addresses, and like the datasheets that quote them — so a decimal int is a
    transcription mistake, not an alternative spelling. And an `expected` with
    bits outside the `mask` can never compare equal, so that probe would
    silently refuse every chip. Either way it must cost that one definition,
    not abort the load and take every other sensor with it.
    """
    document = {
        'sensors': [
            {
                'id': 'broken',
                'label': 'Broken',
                'manufacturer': 'X',
                'addresses': ['0x76'],
                'driver': {'module': 'adafruit_bme280.basic', 'class': 'X'},
                'entities': [
                    {'key': 'temperature', 'attribute': 't', 'name': 'T'},
                ],
                'probe': probe,
            },
            {
                'id': 'fine',
                'label': 'Fine',
                'manufacturer': 'X',
                'addresses': ['0x23'],
                'driver': {'module': 'adafruit_bh1750', 'class': 'BH1750'},
                'entities': [
                    {'key': 'illuminance', 'attribute': 'lux', 'name': 'Light'},
                ],
            },
        ],
    }

    definitions = registry.parse_registry(document)

    assert [definition.id for definition in definitions] == ['fine']


def test_the_bundled_registry_probes_all_pass_validation() -> None:
    """The shipped definitions must not be the thing the new bounds reject."""
    definitions = registry.load_registry()

    assert len(definitions) > 0
    assert any(definition.probe is not None for definition in definitions)


def test_only_the_bundled_registry_is_ever_loaded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A definition is data that decides which class is constructed.

    It names a class, constructor kwargs, attributes to set, methods to call and
    the attribute a reading comes from — only the *module* is allowlisted, so
    everything after `getattr` is whatever the document says. Loading one from
    outside the image needs the trusted channel it would arrive on, so there is
    no second path to prefer.
    """
    planted = tmp_path / 'registry.json'
    planted.write_text('{"sensors": []}')
    monkeypatch.setattr(registry, 'BUNDLED_REGISTRY_PATH', planted)

    # Proves the bundled path is the *only* input: point it somewhere empty and
    # nothing loads, rather than falling back to another location.
    assert registry.load_registry() == ()
    assert not hasattr(registry, 'DOWNLOADED_REGISTRY_PATH')


@pytest.mark.parametrize(
    'key',
    [
        pytest.param('temperature }} {{ states.person', id='template-escape'),
        pytest.param('a.b', id='dotted'),
        pytest.param('', id='empty'),
        pytest.param('2cool', id='not-an-identifier'),
        pytest.param(4, id='not-a-string'),
    ],
)
def test_an_entity_key_must_be_an_identifier(key: object) -> None:
    """The key is interpolated into `{{ value_json.<key> }}` and used on the wire."""
    good = _definition(id='sht4x', addresses=['0x44'], probe=None)
    broken = _definition(
        entities=[{'key': key, 'attribute': 't', 'name': 'T'}],
    )

    definitions = registry.parse_registry({'sensors': [broken, good]})

    assert [definition.id for definition in definitions] == ['sht4x']


@pytest.mark.parametrize(
    'metadata',
    [
        pytest.param({'suggested_display_precision': -1}, id='negative-precision'),
        pytest.param({'suggested_display_precision': True}, id='bool-precision'),
        pytest.param({'suggested_display_precision': '1'}, id='string-precision'),
        pytest.param({'device_class': 3}, id='non-string-device-class'),
        pytest.param({'unit_of_measurement': 3}, id='non-string-unit'),
        pytest.param({'state_class': ['measurement']}, id='non-string-state-class'),
    ],
)
def test_invalid_entity_metadata_drops_only_its_own_definition(
    metadata: dict[str, Any],
) -> None:
    """These fields feed the menu and the discovery payload unescorted.

    A negative `suggested_display_precision` in particular reaches
    `f'{value:.{precision}f}'` inside an autorun selector, and redux does not
    swallow a selector raise — it would take the whole dispatch loop down.
    """
    good = _definition(id='sht4x', addresses=['0x44'], probe=None)
    broken = _definition(
        entities=[
            {
                'key': 'temperature',
                'attribute': 'temperature',
                'name': 'T',
                **metadata,
            },
        ],
    )

    definitions = registry.parse_registry({'sensors': [broken, good]})

    assert [definition.id for definition in definitions] == ['sht4x']


def test_an_entity_index_selects_one_channel_of_a_multi_channel_attribute() -> None:
    """The APDS-9960 reports all four color channels as one `color_data` tuple."""
    (definition,) = registry.parse_registry(
        {
            'sensors': [
                _definition(
                    entities=[
                        {
                            'key': 'red',
                            'attribute': 'color_data',
                            'index': 0,
                            'name': 'Red',
                        },
                        {
                            'key': 'clear',
                            'attribute': 'color_data',
                            'index': 3,
                            'name': 'Clear',
                        },
                    ],
                ),
            ],
        },
    )

    assert [entity.index for entity in definition.entities] == [0, 3]


def test_an_entity_without_an_index_reads_the_attribute_whole() -> None:
    """Indexing is opt-in — a scalar attribute must not be subscripted."""
    (definition,) = registry.parse_registry({'sensors': [_definition()]})

    assert definition.entities[0].index is None


@pytest.mark.parametrize(
    'index',
    [
        pytest.param(-1, id='negative'),
        pytest.param(True, id='bool'),
        pytest.param('0', id='string'),
        pytest.param(1.5, id='float'),
    ],
)
def test_an_invalid_index_drops_only_its_own_definition(index: object) -> None:
    """A negative index reads the wrong end of the tuple and looks plausible."""
    good = _definition(id='sht4x', addresses=['0x44'], probe=None)
    broken = _definition(
        entities=[
            {'key': 'red', 'attribute': 'color_data', 'index': index, 'name': 'Red'},
        ],
    )

    definitions = registry.parse_registry({'sensors': [broken, good]})

    assert [definition.id for definition in definitions] == ['sht4x']


def test_takes_address_defaults_to_true() -> None:
    """Almost every driver takes an address; only the fixed-address ones say so."""
    (definition,) = registry.parse_registry({'sensors': [_definition()]})

    assert definition.driver.takes_address is True


def test_takes_address_false_is_carried_through() -> None:
    """The APDS-9960's address is fixed in silicon and its driver takes none."""
    (definition,) = registry.parse_registry(
        {
            'sensors': [
                _definition(
                    driver={
                        'module': 'adafruit_apds9960.apds9960',
                        'class': 'APDS9960',
                        'takes_address': False,
                    },
                ),
            ],
        },
    )

    assert definition.driver.takes_address is False


def test_a_non_boolean_takes_address_drops_only_its_own_definition() -> None:
    """A truthy string would read as "yes" and mean the opposite of a `false`."""
    good = _definition(id='sht4x', addresses=['0x44'], probe=None)
    broken = _definition(
        driver={
            'module': 'adafruit_bme280.basic',
            'class': 'Adafruit_BME280_I2C',
            'takes_address': 'false',
        },
    )

    definitions = registry.parse_registry({'sensors': [broken, good]})

    assert [definition.id for definition in definitions] == ['sht4x']


def test_min_read_interval_defaults_to_polling_every_tick() -> None:
    """Most sensors have nothing to gain from being asked less often."""
    (definition,) = registry.parse_registry({'sensors': [_definition()]})

    assert definition.min_read_interval == 0.0


def test_min_read_interval_is_carried_through() -> None:
    """A sensor slower than the poll loop declares how slow it actually is."""
    (definition,) = registry.parse_registry(
        {'sensors': [_definition(min_read_interval=5)]},
    )

    assert definition.min_read_interval == 5.0


@pytest.mark.parametrize(
    'interval',
    [
        pytest.param(-1, id='negative'),
        pytest.param('5', id='string'),
        pytest.param(True, id='bool'),
    ],
)
def test_an_invalid_min_read_interval_drops_only_its_own_definition(
    interval: Any,  # noqa: ANN401
) -> None:
    """A bad interval must not cost the user every other sensor.

    A negative one would put `next_read_at` in the past forever, which is not
    obviously wrong at a glance — hence rejecting it at parse time.
    """
    good = _definition(id='sht4x', addresses=['0x44'], probe=None)
    broken = _definition(min_read_interval=interval)

    definitions = registry.parse_registry({'sensors': [broken, good]})

    assert [definition.id for definition in definitions] == ['sht4x']


def test_the_scd4x_is_not_polled_faster_than_it_measures() -> None:
    """The bundled definition, not a synthetic one: this is the whole point.

    The SCD-40 produces a sample every 5 s, and each of its three entities is a
    separate property whose getter checks `data_ready` on the bus. Polled at
    1 Hz it costs 15 round trips per sample it can actually deliver — on the
    most clock-stretch-sensitive device on the bus.
    """
    definitions = {
        definition.id: definition for definition in registry.load_registry()
    }

    assert definitions['scd4x'].min_read_interval >= 5.0


def test_ens160_publishes_its_data_validity_alongside_the_readings() -> None:
    """Its eCO2/TVOC/AQI are meaningless while the sensor is still warming up.

    Publishing the validity state as its own entity lets an automation decide
    what to do about that, rather than the pod silently withholding readings.
    """
    definitions = {
        definition.id: definition for definition in registry.load_registry()
    }
    (validity,) = [
        entity
        for entity in definitions['ens160'].entities
        if entity.key == 'validity'
    ]

    assert validity.attribute == 'data_validity'
    # The driver exposes the raw 0-3 register field, so the template is what
    # turns it into something readable.
    assert validity.value_template is not None
    assert 'warming up' in validity.value_template


def test_a_non_string_value_template_drops_only_its_own_definition() -> None:
    """It is interpolated into a Home Assistant template; it must be text."""
    assert (
        registry.parse_registry(
            {
                'sensors': [
                    {
                        **_definition(),
                        'entities': [
                            {
                                'key': 'a',
                                'attribute': 'a',
                                'name': 'A',
                                'value_template': 3,
                            },
                        ],
                    },
                ],
            },
        )
        == ()
    )
