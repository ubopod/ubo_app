"""Tests for the sensors → Home Assistant entity translation.

`ha.py` is the seam between this service's registry vocabulary
(`EntityDefinition`) and Home Assistant's (`MqttComponent`). It is pure, so the
mapping — including which sensors are announced at all — is pinned here without
a bus or a broker.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.service_loader import load_service_modules
from ubo_app.store.services.sensors import SensorDeviceState, SensorStatus

ha, registry = load_service_modules(
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '040-sensors',
    'ha',
    'registry',
)

BME280 = registry.SensorDefinition(
    id='bme280',
    label='BME280',
    manufacturer='Bosch',
    addresses=(0x76,),
    driver=registry.DriverSpec(module='adafruit_bme280.basic', class_name='X'),
    entities=(
        registry.EntityDefinition(
            key='temperature',
            attribute='temperature',
            name='Temperature',
            device_class='temperature',
            unit_of_measurement='°C',
            state_class='measurement',
            suggested_display_precision=1,
        ),
        registry.EntityDefinition(
            key='humidity',
            attribute='relative_humidity',
            name='Humidity',
            device_class='humidity',
            unit_of_measurement='%',
            state_class='measurement',
        ),
    ),
)

DEFINITIONS = {'bme280': BME280}


def _device(status: SensorStatus = SensorStatus.ACTIVE) -> SensorDeviceState:
    return SensorDeviceState(
        id='bme280_0x76',
        definition_id='bme280',
        label='BME280',
        address=0x76,
        is_builtin=False,
        status=status,
    )


def test_every_entity_of_an_active_device_is_described() -> None:
    """One device contributes one component per registry entity."""
    components = ha.components((_device(),), DEFINITIONS)

    assert [component.component_id for component in components] == [
        'bme280_0x76_temperature',
        'bme280_0x76_humidity',
    ]

    temperature = components[0]
    assert temperature.platform == 'sensor'
    assert temperature.name == 'BME280 Temperature'
    assert temperature.state_channel == 'bme280_0x76/state'
    assert temperature.value_template == '{{ value_json.temperature }}'
    assert temperature.device_class == 'temperature'
    assert temperature.unit_of_measurement == '°C'
    assert temperature.state_class == 'measurement'
    assert temperature.suggested_display_precision == 1
    assert temperature.expire_after == ha.EXPIRE_AFTER


def test_optional_metadata_stays_absent() -> None:
    """An entity without a precision hint must not invent one."""
    _, humidity = ha.components((_device(),), DEFINITIONS)

    assert humidity.suggested_display_precision is None


def test_the_value_template_reads_the_published_key() -> None:
    """The template must read the same key the poll loop publishes."""
    components = ha.components((_device(),), DEFINITIONS)

    for entity, component in zip(BME280.entities, components, strict=True):
        assert component.value_template == f'{{{{ value_json.{entity.key} }}}}'


@pytest.mark.parametrize(
    'status',
    [SensorStatus.ERROR, SensorStatus.UNSUPPORTED, SensorStatus.AMBIGUOUS],
)
def test_only_active_devices_are_described(status: SensorStatus) -> None:
    """A device that failed to initialize has nothing to report."""
    assert ha.components((_device(status),), DEFINITIONS) == []


def test_a_device_with_no_definition_is_skipped() -> None:
    """A registry update could drop a definition out from under a device."""
    assert ha.components((_device(),), {}) == []


def test_the_state_channel_is_relative() -> None:
    """The bridge owns the `ubo/<serial>/` prefix; producers must not add it."""
    assert ha.state_channel('bme280_0x76') == 'bme280_0x76/state'


def test_pmsa003i_announces_three_particulate_entities() -> None:
    """The shipped air-quality sensor maps onto Home Assistant's pm1/pm25/pm10.

    Its driver returns a mapping rather than properties, so this also covers a
    definition whose entity `attribute`s (`pm10 standard`, …) are dict keys and
    deliberately differ from the entity `key`s used in the MQTT payload.
    """
    definitions = {
        definition.id: definition for definition in registry.load_registry()
    }
    device = SensorDeviceState(
        id='pmsa003i_0x12',
        definition_id='pmsa003i',
        label='PMSA003I Air Quality',
        address=0x12,
        is_builtin=False,
        status=SensorStatus.ACTIVE,
    )

    components = ha.components((device,), definitions)

    assert {component.component_id: component.device_class for component in components}\
        == {
            'pmsa003i_0x12_pm1': 'pm1',
            'pmsa003i_0x12_pm25': 'pm25',
            'pmsa003i_0x12_pm10': 'pm10',
        }

    for component in components:
        assert component.unit_of_measurement == 'µg/m³'
        assert component.state_channel == 'pmsa003i_0x12/state'

    # The template reads the entity *key*, which is what the poll loop
    # publishes — not the driver's `pm10 standard` mapping key.
    assert components[0].value_template == '{{ value_json.pm1 }}'


def test_a_definition_may_override_the_value_template() -> None:
    """Some readings are codes, not measurements.

    The ENS160's data-validity register reports 0-3; without an override Home
    Assistant would show a bare number nobody can interpret.
    """
    definition = registry.SensorDefinition(
        id='bme280',
        label='BME280',
        manufacturer='Bosch',
        addresses=(0x76,),
        driver=registry.DriverSpec(module='adafruit_bme280.basic', class_name='X'),
        entities=(
            registry.EntityDefinition(
                key='validity',
                attribute='data_validity',
                name='Data Validity',
                value_template='{{ value_json.validity }}!',
            ),
        ),
    )

    (component,) = ha.components((_device(),), {'bme280': definition})

    assert component.value_template == '{{ value_json.validity }}!'
