"""Tests for the infrared service's Home Assistant entities.

Two directions, both easy to get silently wrong: a button that carries a raw
code instead of a registry identifier would let a remote caller transmit
anything, and an event payload whose `event_type` is not in the declared list is
discarded by Home Assistant without complaint.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.service_loader import load_service_modules
from ubo_app.store.services.infrared import InfraredDevice

(ha,) = load_service_modules(
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '090-infrared',
    'ha',
)

TV = InfraredDevice(name='TV Power', protocol='nec', scancode='0x40')
AMP = InfraredDevice(name='Amp Volume Up', protocol='necx', scancode='0xbf10')


def _by_id(devices: list[InfraredDevice]) -> dict[str, Any]:
    return {
        component.component_id: component for component in ha.components(devices)
    }


def test_each_registered_device_gets_a_button() -> None:
    """One button per device the user already taught the pod."""
    components = _by_id([TV, AMP])

    assert set(components) == {
        'ir_received',
        'ir_send_tv_power_nec_0x40',
        'ir_send_amp_volume_up_necx_0xbf10',
    }
    assert components['ir_send_tv_power_nec_0x40'].platform == 'button'
    assert components['ir_send_tv_power_nec_0x40'].name == 'TV Power'


def test_devices_sharing_a_code_get_distinct_buttons() -> None:
    """Two differently-named devices can share a `protocol:scancode`.

    An id derived from the code alone would collapse them into one component;
    only the (name, code) pair tells them apart.
    """
    twin = InfraredDevice(name='Bedroom TV Power', protocol='nec', scancode='0x40')
    components = _by_id([TV, twin])

    assert 'ir_send_tv_power_nec_0x40' in components
    assert 'ir_send_bedroom_tv_power_nec_0x40' in components


def test_a_button_carries_an_identifier_not_a_raw_code() -> None:
    """`payload_press` is looked up in the registry, never transmitted as-is.

    This is what makes "send infrared" an allowlist: the pod receives the name
    of something it already knows rather than a code to blindly emit.
    """
    assert _by_id([TV])['ir_send_tv_power_nec_0x40'].payload_press == 'nec:0x40'


def test_buttons_are_never_retained() -> None:
    """A retained press would re-fire on every reconnect."""
    assert _by_id([TV])['ir_send_tv_power_nec_0x40'].retain is False


def test_the_event_entity_declares_every_device_name() -> None:
    """Home Assistant discards an event whose type it was not told about."""
    event = _by_id([TV, AMP])['ir_received']

    assert event.platform == 'event'
    assert event.state_channel == 'ir/received'
    assert event.event_types == ('TV Power', 'Amp Volume Up', 'unknown')


def test_the_event_entity_exists_with_no_devices_registered() -> None:
    """An unrecognised remote is still worth reporting."""
    event = _by_id([])['ir_received']

    assert event.event_types == ('unknown',)


def test_duplicate_device_names_are_declared_once() -> None:
    """Names are not unique — only the code is — but event types must be."""
    twin = InfraredDevice(name='TV Power', protocol='nec', scancode='0x41')
    event = _by_id([TV, twin])['ir_received']

    assert event.event_types == ('TV Power', 'unknown')


def test_a_known_code_is_reported_under_its_device_name() -> None:
    """An automation should react to "TV Power", not to a hex scancode."""
    payload = json.loads(ha.received_payload('nec', '0x40', [TV, AMP]))

    assert payload == {
        'event_type': 'TV Power',
        'protocol': 'nec',
        'scancode': '0x40',
    }


def test_an_unknown_code_is_reported_as_unknown() -> None:
    """Inventing an event type would get the whole event discarded."""
    payload = json.loads(ha.received_payload('sony', '0x99', [TV]))

    assert payload['event_type'] == 'unknown'
    assert payload['protocol'] == 'sony'
    assert payload['scancode'] == '0x99'


def test_the_reported_event_type_is_always_declared() -> None:
    """The two halves of the contract have to agree, or events vanish."""
    devices = [TV, AMP]
    declared = set(_by_id(devices)['ir_received'].event_types)

    for protocol, scancode in (('nec', '0x40'), ('necx', '0xbf10'), ('x', 'y')):
        payload = json.loads(ha.received_payload(protocol, scancode, devices))
        assert payload['event_type'] in declared
