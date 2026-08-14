"""Tests for the Sensors menu projection and the persistence selector.

Both exist to answer the same question — *what changes when a reading lands?*
— and the answer has to be "nothing". `register_persistent_store` and the
device-list menu are both autoruns: if a reading were visible in their
selectors, every tick would rewrite `state.json` on the SD card and re-render
the menu, once a second, forever.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fake import Fake

from tests.service_loader import load_service_modules
from ubo_app.store.core.types import MenuStackItem, RenderStackItem
from ubo_app.store.services.sensors import (
    SensorDeviceState,
    SensorEntityReading,
    SensorsState,
    SensorStatus,
)

# `setup` opens the I2C bus at import; off-device the app fakes `board` in
# `setup_headless`, and the test environment has to do the same.
sys.modules.setdefault('board', Fake())

menu, setup = load_service_modules(
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '040-sensors',
    'menu',
    'setup',
)


@pytest.fixture(autouse=True)
def _armed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the gate in front of the selector; these test the projection.

    `persistence_selector` answers `None` until the restore has landed — see
    `tests/store/test_sensors_lifecycle.py`.
    """
    monkeypatch.setattr(setup, '_is_armed', True)


def _device(
    definition_id: str,
    address: int,
    *,
    is_builtin: bool = False,
    entities: tuple[SensorEntityReading, ...] = (),
) -> SensorDeviceState:
    return SensorDeviceState(
        id=f'{definition_id}_{address:#04x}',
        definition_id=definition_id,
        label=definition_id.upper(),
        address=address,
        is_builtin=is_builtin,
        status=SensorStatus.ACTIVE,
        entities=entities,
    )


def _state(*devices: SensorDeviceState) -> SensorsState:
    return SensorsState(devices={device.id: device for device in devices})


@pytest.mark.parametrize(
    ('path', 'expected'),
    [
        (('', '', '', 'sensors:'), 'sensors:settings'),
        (('', '', '', 'camera:'), None),
        (('', '', ''), None),
    ],
)
def test_path_matcher(path: tuple[str, ...], expected: str | None) -> None:
    """The matcher resolves the device list. Readings are a render view, not a menu."""
    assert menu._path_matcher(path) == expected  # noqa: SLF001


def test_identity_projection_ignores_readings() -> None:
    """A new reading must not change the device-list selector's output.

    This is what keeps the menu from re-rendering at 1 Hz.
    """
    device = _device('bme280', 0x76)
    before = menu._identities(_state(device))  # noqa: SLF001

    with_reading = replace(
        device,
        entities=(SensorEntityReading(key='temperature', value=22.5),),
    )
    after = menu._identities(_state(with_reading))  # noqa: SLF001

    assert before == after


def test_identity_projection_reacts_to_a_new_device() -> None:
    """It does still change when the device set changes — otherwise it's useless."""
    first = _device('bme280', 0x76)
    before = menu._identities(_state(first))  # noqa: SLF001
    after = menu._identities(_state(first, _device('sht4x', 0x44)))  # noqa: SLF001

    assert before != after
    assert len(after) == 2


def test_identity_projection_lists_builtins_first() -> None:
    """Built-ins lead the list; the rest follow by address."""
    identities = menu._identities(  # noqa: SLF001
        _state(
            _device('sht4x', 0x44),
            _device('bme280', 0x76),
            _device('pct2075', 0x48, is_builtin=True),
        ),
    )

    assert [identity.id for identity in identities] == [
        'pct2075_0x48',
        'sht4x_0x44',
        'bme280_0x76',
    ]


# --------------------------------------------------------------------------
# The readings page
# --------------------------------------------------------------------------


@pytest.fixture
def _shipped_definitions(monkeypatch: pytest.MonkeyPatch) -> Any:  # noqa: ANN401
    """Point the menu at the real bundled registry."""
    (registry,) = load_service_modules(
        Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '040-sensors',
        'registry',
    )
    definitions = {
        definition.id: definition for definition in registry.load_registry()
    }
    monkeypatch.setattr(menu, '_definitions', definitions)
    return definitions


@pytest.mark.usefixtures('_shipped_definitions')
def test_reading_rows_carry_names_units_and_registry_precision() -> None:
    """The page shows what a menu row cannot: a name, a value and a unit.

    Precision comes from the registry — a CO2 reading rendered as `412.00 ppm`
    or a pressure as `1013 hPa` would both be wrong.
    """
    device = SensorDeviceState(
        id='scd4x_0x62',
        definition_id='scd4x',
        label='SCD-40 CO2',
        address=0x62,
        is_builtin=False,
        status=SensorStatus.ACTIVE,
        entities=(
            SensorEntityReading(key='co2', value=412.4),
            SensorEntityReading(key='temperature', value=21.83),
            SensorEntityReading(key='humidity', value=45.2),
        ),
    )

    labels, values, units, keys, device_classes = menu._reading_rows(  # noqa: SLF001
        device,
        menu.UnitSystem.METRIC,
    )

    assert labels == ('CO2', 'Temperature', 'Humidity')
    assert units == ('ppm', '°C', '%')
    # precision 0 / 1 / 0 from the registry
    assert values == ('412', '21.8', '45')
    assert keys == ('co2', 'temperature', 'humidity')
    assert device_classes == ('carbon_dioxide', 'temperature', 'humidity')


@pytest.mark.usefixtures('_shipped_definitions')
def test_a_missing_reading_renders_as_a_dash_not_a_zero() -> None:
    """An unread entity must not be shown as 0 — that is a plausible reading."""
    device = SensorDeviceState(
        id='bme680_0x77',
        definition_id='bme680',
        label='BME680',
        address=0x77,
        is_builtin=False,
        status=SensorStatus.ACTIVE,
        entities=(SensorEntityReading(key='temperature', value=None),),
    )

    labels, values, units, keys, device_classes = menu._reading_rows(  # noqa: SLF001
        device,
        menu.UnitSystem.METRIC,
    )

    assert labels == ('Temperature', 'Humidity', 'Pressure', 'Gas Resistance')
    assert values[0] == menu.UNKNOWN_VALUE
    # Entities the device did not report at all are still listed, as unknown.
    assert set(values[1:]) == {menu.UNKNOWN_VALUE}
    assert units == ('°C', '%', 'hPa', 'Ω')
    assert keys == ('temperature', 'humidity', 'pressure', 'gas_resistance')
    # gas_resistance has no device_class in the registry — empty, not None,
    # since props values must be BasicType.
    assert device_classes == ('temperature', 'humidity', 'pressure', '')


@pytest.mark.usefixtures('_shipped_definitions')
def test_reading_rows_converts_temperature_for_us() -> None:
    """A temperature entity converts to Fahrenheit under the US unit system."""
    device = SensorDeviceState(
        id='scd4x_0x62',
        definition_id='scd4x',
        label='SCD-40 CO2',
        address=0x62,
        is_builtin=False,
        status=SensorStatus.ACTIVE,
        entities=(
            SensorEntityReading(key='co2', value=412.4),
            SensorEntityReading(key='temperature', value=20.0),
            SensorEntityReading(key='humidity', value=45.2),
        ),
    )

    labels, values, units, keys, device_classes = menu._reading_rows(  # noqa: SLF001
        device,
        menu.UnitSystem.US,
    )

    assert dict(zip(labels, zip(values, units, strict=True), strict=True)) == {
        'CO2': ('412', 'ppm'),  # no US-customary equivalent — unchanged
        'Temperature': ('68.0', '°F'),
        'Humidity': ('45', '%'),  # no US-customary equivalent — unchanged
    }
    assert keys == ('co2', 'temperature', 'humidity')
    assert device_classes == ('carbon_dioxide', 'temperature', 'humidity')


@pytest.mark.usefixtures('_shipped_definitions')
def test_reading_rows_converts_distance_by_source_unit_independently() -> None:
    """bmp388's altitude ('m') and vl53l1x's proximity ('cm') convert independently.

    'distance' means different source units on different sensors in this
    registry, so each must convert on its own under US units.
    """
    bmp388 = SensorDeviceState(
        id='bmp388_0x77',
        definition_id='bmp388',
        label='BMP388',
        address=0x77,
        is_builtin=False,
        status=SensorStatus.ACTIVE,
        entities=(
            SensorEntityReading(key='pressure', value=1013.25),
            SensorEntityReading(key='temperature', value=20.0),
            SensorEntityReading(key='altitude', value=100.0),
        ),
    )
    vl53l1x = SensorDeviceState(
        id='vl53l1x_0x29',
        definition_id='vl53l1x',
        label='VL53L1X',
        address=0x29,
        is_builtin=False,
        status=SensorStatus.ACTIVE,
        entities=(SensorEntityReading(key='distance', value=30.0),),
    )

    bmp_rows = menu._reading_rows(bmp388, menu.UnitSystem.US)  # noqa: SLF001
    bmp_units, bmp_keys = bmp_rows[2], bmp_rows[3]
    assert dict(zip(bmp_keys, bmp_units, strict=True))['altitude'] == 'ft'

    vl_rows = menu._reading_rows(vl53l1x, menu.UnitSystem.US)  # noqa: SLF001
    vl_values, vl_units, vl_keys = vl_rows[1], vl_rows[2], vl_rows[3]
    assert dict(zip(vl_keys, vl_units, strict=True))['distance'] == 'in'
    assert vl_values[vl_keys.index('distance')] != '30.0'  # actually converted


@pytest.mark.usefixtures('_shipped_definitions')
def test_reading_rows_metric_is_passthrough_for_already_metric_values() -> None:
    """UnitSystem.METRIC never mutates already-metric registry values."""
    device = SensorDeviceState(
        id='bmp388_0x77',
        definition_id='bmp388',
        label='BMP388',
        address=0x77,
        is_builtin=False,
        status=SensorStatus.ACTIVE,
        entities=(
            SensorEntityReading(key='pressure', value=1013.25),
            SensorEntityReading(key='temperature', value=20.0),
            SensorEntityReading(key='altitude', value=100.0),
        ),
    )

    rows = menu._reading_rows(device, menu.UnitSystem.METRIC)  # noqa: SLF001
    values, units = rows[1], rows[2]

    assert units == ('hPa', '°C', 'm')
    assert values == ('1013.25', '20.0', '100.0')


@pytest.mark.usefixtures('_shipped_definitions')
def test_opening_an_active_sensor_opens_its_readings_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selecting a sensor pushes a `readings` render view keyed by its stream id."""
    dispatched: list[Any] = []
    monkeypatch.setattr(
        menu.store,
        'dispatch',
        lambda *actions: dispatched.extend(actions),
    )

    menu._open_device(  # noqa: SLF001
        menu._Identity(  # noqa: SLF001
            id='bmp388_0x77',
            definition_id='bmp388',
            label='BMP388 Pressure',
            status=SensorStatus.ACTIVE,
            address=0x77,
            is_builtin=False,
        ),
    )

    (action,) = dispatched
    assert action.kind == 'readings'
    assert action.title == 'BMP388 Pressure'
    assert action.stream_id == 'sensors:readings:bmp388_0x77'
    assert action.props['labels'] == ('Pressure', 'Temperature', 'Altitude')
    assert action.props['units'] == ('hPa', '°C', 'm')
    # Values are unknown until the poll loop's next tick fills them in.
    assert set(action.props['values']) == {menu.UNKNOWN_VALUE}
    assert action.props['keys'] == ('pressure', 'temperature', 'altitude')
    assert action.props['device_classes'] == ('pressure', 'temperature', 'distance')


@pytest.mark.usefixtures('_shipped_definitions')
def test_opening_a_broken_sensor_explains_itself_instead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sensor that failed to init has no readings — say why, don't show a blank."""
    dispatched: list[Any] = []
    monkeypatch.setattr(
        menu.store,
        'dispatch',
        lambda *actions: dispatched.extend(actions),
    )

    menu._open_device(  # noqa: SLF001
        menu._Identity(  # noqa: SLF001
            id='bmp388_0x77',
            definition_id='bmp388',
            label='BMP388 Pressure',
            status=SensorStatus.ERROR,
            address=0x77,
            is_builtin=False,
        ),
    )

    (action,) = dispatched
    assert action.kind == 'status'
    assert action.props['text'] == menu._STATUS_HINTS[SensorStatus.ERROR]  # noqa: SLF001


def _root_state(*devices: SensorDeviceState) -> Any:  # noqa: ANN401
    return SimpleNamespace(sensors=_state(*devices))


def test_persistence_selector_ignores_readings() -> None:
    """A reading must not change the persisted value.

    `register_persistent_store` autoruns on this selector, so if a reading
    were visible here every tick would rewrite `state.json` on the SD card.
    """
    device = _device('bme280', 0x76)
    before = setup.persistence_selector(_root_state(device))

    with_reading = replace(
        device,
        entities=(SensorEntityReading(key='temperature', value=22.5),),
    )
    after = setup.persistence_selector(_root_state(with_reading))

    assert before == after
    assert json.loads(before) == [{'definition_id': 'bme280', 'address': 0x76}]


def test_persistence_selector_omits_builtins_and_unidentified_devices() -> None:
    """Built-ins come back from the EEPROM; an unrecognized device has no identity."""
    persisted = json.loads(
        setup.persistence_selector(
            _root_state(
                _device('pct2075', 0x48, is_builtin=True),
                _device('', 0x62),
                _device('sht4x', 0x44),
            ),
        ),
    )

    assert persisted == [{'definition_id': 'sht4x', 'address': 0x44}]


def test_persistence_selector_reacts_to_a_new_device() -> None:
    """It does change when the device set changes."""
    before = setup.persistence_selector(_root_state(_device('sht4x', 0x44)))
    after = setup.persistence_selector(
        _root_state(_device('sht4x', 0x44), _device('bme280', 0x76)),
    )

    assert before != after


@pytest.mark.parametrize(
    'stored',
    [
        pytest.param('not json at all', id='not-json'),
        pytest.param('{"definition_id": "bme280"}', id='object-not-list'),
        pytest.param('[["bme280", 118]]', id='entries-are-not-objects'),
        pytest.param('[{"definition_id": "bme280"}]', id='no-address'),
        pytest.param(
            '[{"definition_id": "bme280", "address": "0x76"}]',
            id='hex-string',
        ),
        pytest.param(
            '[{"definition_id": "bme280", "address": null}]',
            id='null-address',
        ),
        pytest.param(
            '[{"definition_id": "gone", "address": 118}]',
            id='unknown-definition',
        ),
    ],
)
def test_a_malformed_persisted_device_list_does_not_abort_startup(
    stored: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_persisted_matches` runs during service start-up.

    A hand-edited or truncated `state.json` must cost the user the sensors it
    describes, not the whole service — raising here would terminate
    `_initialize()` before anything came up.
    """
    monkeypatch.setattr(
        setup,
        'read_from_persistent_store',
        lambda *_args, **_kwargs: json.loads(stored),
    )

    assert setup._persisted_matches() == ()  # noqa: SLF001


def test_a_well_formed_persisted_device_is_reattached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard must not throw away the entries it exists to restore."""
    (registry,) = load_service_modules(
        Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '040-sensors',
        'registry',
    )
    definitions = tuple(registry.load_registry())
    monkeypatch.setattr(setup, '_definitions', definitions)
    monkeypatch.setattr(
        setup,
        'read_from_persistent_store',
        lambda *_args, **_kwargs: [{'definition_id': 'bme280', 'address': 0x76}],
    )

    (match,) = setup._persisted_matches()  # noqa: SLF001

    assert match.address == 0x76
    assert match.definition is not None
    assert match.definition.id == 'bme280'


@pytest.mark.parametrize(
    ('address', 'why'),
    [
        pytest.param(0x1A, 'the WM8960 audio codec', id='reserved-codec'),
        pytest.param(0x50, 'the HAT EEPROM', id='reserved-eeprom'),
        pytest.param(0x58, 'the keypad GPIO expander', id='reserved-keypad'),
        pytest.param(0x44, 'an address bme280 does not claim', id='not-claimed'),
    ],
)
def test_a_persisted_device_at_an_unsafe_address_is_refused(
    address: int,
    why: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A persisted address goes straight to a driver constructor.

    It skips the scan, which refuses to so much as *probe* on-board hardware —
    a probe writes a register pointer, and a stray byte to the audio codec is a
    partial register write. A corrupted entry must not get past that.
    """
    _ = why
    (registry,) = load_service_modules(
        Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '040-sensors',
        'registry',
    )
    monkeypatch.setattr(setup, '_definitions', tuple(registry.load_registry()))
    monkeypatch.setattr(
        setup,
        'read_from_persistent_store',
        lambda *_args, **_kwargs: [
            {'definition_id': 'bme280', 'address': address},
        ],
    )

    assert setup._persisted_matches() == ()  # noqa: SLF001


def test_a_persisted_device_at_a_builtin_address_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The on-board sensors come from the EEPROM, and own their addresses."""
    (registry,) = load_service_modules(
        Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '040-sensors',
        'registry',
    )
    monkeypatch.setattr(setup, '_definitions', tuple(registry.load_registry()))
    monkeypatch.setattr(
        setup,
        'read_from_persistent_store',
        lambda *_args, **_kwargs: [
            {'definition_id': 'bme280', 'address': 0x76},
        ],
    )

    assert setup._persisted_matches(frozenset({0x76})) == ()  # noqa: SLF001


def _stack_state(
    *devices: SensorDeviceState,
    stack: tuple[Any, ...] = (),
) -> Any:  # noqa: ANN401
    return SimpleNamespace(sensors=_state(*devices), main=SimpleNamespace(stack=stack))


def _readings_page(device_id: str) -> RenderStackItem:
    return RenderStackItem(
        id='r1',
        kind='readings',
        stream_id=f'sensors:readings:{device_id}',
    )


@pytest.mark.usefixtures('_shipped_definitions')
def test_no_open_readings_page_selects_nothing() -> None:
    """The whole point of the selector.

    Every sensor dispatches its own reading each second and each replaces the
    device mapping. Reacting to that by dispatching per device would be N²
    actions a second — spent entirely on pages nobody is looking at.
    """
    device = _device(
        'bme280',
        0x76,
        entities=(SensorEntityReading(key='temperature', value=22.5),),
    )

    assert menu._open_readings(_stack_state(device)) is None  # noqa: SLF001
    assert (
        menu._open_readings(  # noqa: SLF001
            _stack_state(device, stack=(MenuStackItem(id='m1', menu_key='sensors:'),)),
        )
        is None
    )


@pytest.mark.usefixtures('_shipped_definitions')
def test_only_the_open_sensor_is_selected() -> None:
    """One page is open; the other sensors' readings are not the selector's business."""
    open_device = _device(
        'sht4x',
        0x44,
        entities=(
            SensorEntityReading(key='temperature', value=21.0),
            SensorEntityReading(key='humidity', value=48.0),
        ),
    )
    other = _device(
        'bme280',
        0x76,
        entities=(SensorEntityReading(key='temperature', value=30.0),),
    )

    selected = menu._open_readings(  # noqa: SLF001
        _stack_state(open_device, other, stack=(_readings_page('sht4x_0x44'),)),
    )

    assert selected == (
        'sensors:readings:sht4x_0x44',
        ('Temperature', 'Humidity'),
        # Precision comes from the registry: one decimal for temperature, none
        # for relative humidity.
        ('21.0', '48'),
        ('°C', '%'),
        ('temperature', 'humidity'),
        ('temperature', 'humidity'),
    )


@pytest.mark.usefixtures('_shipped_definitions')
def test_another_sensors_reading_does_not_wake_the_open_page() -> None:
    """Equal selector output is what stops the autorun re-dispatching."""
    open_device = _device(
        'sht4x',
        0x44,
        entities=(SensorEntityReading(key='temperature', value=21.0),),
    )
    other = _device('bme280', 0x76)
    stack = (_readings_page('sht4x_0x44'),)

    before = menu._open_readings(_stack_state(open_device, other, stack=stack))  # noqa: SLF001
    after = menu._open_readings(  # noqa: SLF001
        _stack_state(
            open_device,
            replace(
                other,
                entities=(SensorEntityReading(key='temperature', value=31.0),),
            ),
            stack=stack,
        ),
    )

    assert before == after


@pytest.mark.usefixtures('_shipped_definitions')
def test_the_open_sensors_own_reading_does_wake_it() -> None:
    """It still has to update once a second — that is the page's whole job."""
    device = _device(
        'sht4x',
        0x44,
        entities=(SensorEntityReading(key='temperature', value=21.0),),
    )
    stack = (_readings_page('sht4x_0x44'),)

    before = menu._open_readings(_stack_state(device, stack=stack))  # noqa: SLF001
    after = menu._open_readings(  # noqa: SLF001
        _stack_state(
            replace(
                device,
                entities=(SensorEntityReading(key='temperature', value=21.4),),
            ),
            stack=stack,
        ),
    )

    assert before != after


@pytest.mark.usefixtures('_shipped_definitions')
def test_a_sensor_that_went_away_selects_nothing() -> None:
    """A re-scan can drop the device whose page is open."""
    assert (
        menu._open_readings(  # noqa: SLF001
            _stack_state(stack=(_readings_page('sht4x_0x44'),)),
        )
        is None
    )


@pytest.mark.usefixtures('_shipped_definitions')
def test_the_topmost_readings_page_wins() -> None:
    """Only one is on screen, and it is the one nearest the top of the stack."""
    first = _device('bme280', 0x76)
    second = _device('sht4x', 0x44)

    selected = menu._open_readings(  # noqa: SLF001
        _stack_state(
            first,
            second,
            stack=(
                _readings_page('bme280_0x76'),
                _readings_page('sht4x_0x44'),
            ),
        ),
    )

    assert selected is not None
    assert selected[0] == 'sensors:readings:sht4x_0x44'


@pytest.mark.usefixtures('_shipped_definitions')
def test_a_readings_page_buried_under_another_item_selects_nothing() -> None:
    """A page that is not on top of the stack is not on screen.

    Pushing 1 Hz updates to it anyway — from under a notification, say — would
    re-render every connected client for a page nobody can see.
    """
    device = _device(
        'sht4x',
        0x44,
        entities=(SensorEntityReading(key='temperature', value=21.0),),
    )

    assert (
        menu._open_readings(  # noqa: SLF001
            _stack_state(
                device,
                stack=(
                    _readings_page('sht4x_0x44'),
                    MenuStackItem(id='m1', menu_key='notifications:'),
                ),
            ),
        )
        is None
    )


@pytest.mark.usefixtures('_shipped_definitions')
def test_the_reaction_dispatches_one_update_for_the_open_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One page open, one action — not one per sensor on the bus."""
    dispatched: list[Any] = []
    monkeypatch.setattr(
        menu.store,
        'dispatch',
        lambda *actions: dispatched.extend(actions),
    )

    menu._update_open_readings(None)  # noqa: SLF001
    assert dispatched == []

    menu._update_open_readings(  # noqa: SLF001
        (
            'sensors:readings:sht4x_0x44',
            ('Temperature',),
            ('21.0',),
            ('°C',),
            ('temperature',),
            ('temperature',),
        ),
    )

    (action,) = dispatched
    assert action.stream_id == 'sensors:readings:sht4x_0x44'
    assert action.props == {
        'labels': ('Temperature',),
        'values': ('21.0',),
        'units': ('°C',),
        'keys': ('temperature',),
        'device_classes': ('temperature',),
    }
