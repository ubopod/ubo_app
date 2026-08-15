"""Tests for the Home Assistant MQTT discovery payload.

`build_discovery_payload` is the contract with Home Assistant: get a key wrong
and the entity silently never appears. It is pure, so it is pinned here against
a golden payload.

NOTE: the bridge lives under ``ubo_app/services/050-mqtt``, which is not an
importable package path, so the service directory goes on ``sys.path`` before
importing — same pattern as ``test_sensors_reducer.py``.
"""

from __future__ import annotations

from pathlib import Path

from tests.service_loader import load_service_modules
from ubo_app.store.services.mqtt import MqttComponent

_M = load_service_modules(
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '050-mqtt',
    'discovery', 'topics',
)
discovery, topics = _M


TEMPERATURE = MqttComponent(
    component_id='bme280_0x76_temperature',
    platform='sensor',
    name='BME280 Temperature',
    state_channel='bme280_0x76/state',
    value_template='{{ value_json.temperature }}',
    expire_after=30,
    device_class='temperature',
    unit_of_measurement='°C',
    state_class='measurement',
    suggested_display_precision=1,
)
HUMIDITY = MqttComponent(
    component_id='bme280_0x76_humidity',
    platform='sensor',
    name='BME280 Humidity',
    state_channel='bme280_0x76/state',
    value_template='{{ value_json.humidity }}',
    expire_after=30,
    device_class='humidity',
    unit_of_measurement='%',
    state_class='measurement',
)


def test_discovery_payload_declares_every_entity() -> None:
    """One device-level payload announces every contributed entity."""
    payload = discovery.build_discovery_payload('abc', (TEMPERATURE, HUMIDITY))

    assert payload['dev']['ids'] == ['ubo_abc']
    assert payload['avty_t'] == 'ubo/abc/availability'
    assert payload['o']['name'] == 'ubo-app'

    assert set(payload['cmps']) == {
        'bme280_0x76_temperature',
        'bme280_0x76_humidity',
    }

    assert payload['cmps']['bme280_0x76_temperature'] == {
        'p': 'sensor',
        'unique_id': 'ubo_abc_bme280_0x76_temperature',
        'name': 'BME280 Temperature',
        'stat_t': 'ubo/abc/bme280_0x76/state',
        'val_tpl': '{{ value_json.temperature }}',
        'exp_aft': 30,
        'dev_cla': 'temperature',
        'unit_of_meas': '°C',
        'stat_cla': 'measurement',
        'sug_dsp_prc': 1,
    }


def test_optional_metadata_is_omitted_not_nulled() -> None:
    """Home Assistant treats an explicit null differently from an absent key."""
    payload = discovery.build_discovery_payload('abc', (HUMIDITY,))
    humidity = payload['cmps']['bme280_0x76_humidity']

    assert 'sug_dsp_prc' not in humidity
    assert humidity['unit_of_meas'] == '%'


def test_a_minimal_component_renders_only_the_required_keys() -> None:
    """A zero-field button needs nothing beyond platform/id/name."""
    payload = discovery.build_discovery_payload(
        'abc',
        (MqttComponent(component_id='chime', platform='button', name='Chime'),),
    )

    assert payload['cmps']['chime'] == {
        'p': 'button',
        'unique_id': 'ubo_abc_chime',
        'name': 'Chime',
    }


def test_command_channels_and_sequences_render() -> None:
    """Commandable and enumerated entities carry their extra discovery keys."""
    payload = discovery.build_discovery_payload(
        'abc',
        (
            MqttComponent(
                component_id='play_chime',
                platform='select',
                name='Play Chime',
                command_channel='cmd/audio:play_chime',
                payload_press='PRESS',
                options=('add', 'done'),
                event_types=('pressed',),
            ),
        ),
    )

    component = payload['cmps']['play_chime']
    assert component['cmd_t'] == 'ubo/abc/cmd/audio:play_chime'
    assert component['pl_prs'] == 'PRESS'
    assert component['ops'] == ['add', 'done']
    assert component['evt_typ'] == ['pressed']


def test_no_components_still_announces_the_device() -> None:
    """An empty pod is still a device Home Assistant should know about."""
    payload = discovery.build_discovery_payload('abc', ())

    assert payload['cmps'] == {}
    assert payload['dev']['ids'] == ['ubo_abc']


def test_a_removal_keeps_the_platform_key() -> None:
    """A removal payload must still carry `p`, or Home Assistant ignores it.

    The discovery docs are explicit: "An empty config can be published as an
    update to remove a single component from the device discovery. Note that
    adding the `platform` (`p`) option is still required." A bare `{}` is
    silently discarded and the unplugged sensor lingers on the dashboard as
    "unavailable" forever.
    """
    payload = discovery.build_discovery_payload(
        'abc',
        (),
        removed_components={'bme280_0x76_temperature': 'sensor'},
    )

    assert payload['cmps'] == {'bme280_0x76_temperature': {'p': 'sensor'}}


def test_a_removal_carries_the_platform_it_was_published_with() -> None:
    """Retiring a button must say `button`, not a hardcoded `sensor`."""
    payload = discovery.build_discovery_payload(
        'abc',
        (),
        removed_components={'ring_off': 'button', 'chime': 'select'},
    )

    assert payload['cmps'] == {
        'ring_off': {'p': 'button'},
        'chime': {'p': 'select'},
    }


def test_a_removal_never_clobbers_a_live_component() -> None:
    """A component that is both live and listed as removed stays live."""
    payload = discovery.build_discovery_payload(
        'abc',
        (TEMPERATURE,),
        removed_components={'bme280_0x76_temperature': 'sensor'},
    )

    assert payload['cmps']['bme280_0x76_temperature'] != {'p': 'sensor'}
    assert payload['cmps']['bme280_0x76_temperature']['dev_cla'] == 'temperature'


def test_component_platforms_drive_the_removal_diff() -> None:
    """The bridge keeps this from the last announce to diff against the next.

    It maps id -> platform rather than being a bare set of ids, because the
    removal payload has to repeat the platform.
    """
    assert discovery.component_platforms((TEMPERATURE, HUMIDITY)) == {
        'bme280_0x76_temperature': 'sensor',
        'bme280_0x76_humidity': 'sensor',
    }
    assert discovery.component_platforms(()) == {}
