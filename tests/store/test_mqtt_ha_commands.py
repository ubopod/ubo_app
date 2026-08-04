"""Tests for the command entities' Home Assistant discovery shape.

A wrong or missing discovery key fails *silently* — the entity either never
appears or appears and does nothing — so the rendered payload is pinned here as
a literal rather than rebuilt from the same expressions the code uses.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.service_loader import load_service_modules

_M = load_service_modules(
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '050-mqtt',
    'ha_commands', 'discovery', 'commands',
)
ha_commands, discovery, commands = _M


def _rendered() -> dict[str, Any]:
    payload = discovery.build_discovery_payload(
        'abc',
        ha_commands.components(),
    )
    return payload['cmps']


def test_the_notify_entity_declares_only_a_command_topic() -> None:
    """No `cmd_tpl`: the platform publishes the raw message text.

    The docs do not say which variables a `command_template` would receive, and
    a wrong guess renders an entity that silently never works.
    """
    assert _rendered()['cmd_notify'] == {
        'p': 'notify',
        'unique_id': 'ubo_abc_cmd_notify',
        'name': 'Notification',
        'cmd_t': 'ubo/abc/command/notify',
        'ret': False,
        'qos': 0,
    }


def test_the_chime_entity_carries_its_options() -> None:
    """`options` is required for a select; without it there is nothing to pick."""
    chime = _rendered()['cmd_chime']

    assert chime['p'] == 'select'
    assert chime['cmd_t'] == 'ubo/abc/command/chime'
    assert chime['ops'] == ['add', 'done', 'failure', 'volume']


def test_the_brightness_entity_declares_its_range() -> None:
    """Home Assistant defaults a number to min 1, max 100, step 1.

    Leaving them unset would render a 1-100 integer slider and publish values
    the pod refuses, so these are not optional.
    """
    brightness = _rendered()['cmd_ring_brightness']

    assert brightness['p'] == 'number'
    assert brightness['min'] == 0
    assert brightness['max'] == 1
    assert brightness['step'] == 0.05
    assert brightness['mode'] == 'slider'


def test_the_ring_off_entity_is_a_button() -> None:
    """A button publishes `payload_press`; the pod ignores the value."""
    ring_off = _rendered()['cmd_ring_off']

    assert ring_off['p'] == 'button'
    assert ring_off['pl_prs'] == 'PRESS'
    assert ring_off['cmd_t'] == 'ubo/abc/command/ring.off'


def test_no_command_entity_is_ever_retained() -> None:
    """A retained command replays on every reconnect, forever."""
    assert all(component['ret'] is False for component in _rendered().values())


def test_colour_gets_no_entity() -> None:
    """Three channels need a `light`, whose payload shape is HA's, not raw RGB.

    A real light would also have to report state back, and `RgbRingState` holds
    only `is_busy`. Colour stays an automation-driven topic instead.
    """
    assert 'cmd_ring_color' not in _rendered()




# Commands this module deliberately does not render an entity for.
_ENTITY_LESS = {
    # Three channels need a `light`; see `test_colour_gets_no_entity`.
    'ring.color',
    # Contributed by `090-infrared` instead — one button per *registered*
    # device, each carrying its own code as `payload_press`. The set is dynamic,
    # so it cannot live in this module's static table.
    'ir.send',
    # No entity: `notify.send_message` cannot carry chime/blink/colour, so the
    # rich form is driven from an automation with `mqtt.publish`.
    'notify.rich',
}


def test_every_entity_maps_to_a_real_command() -> None:
    """An entity pointing at a topic nothing handles is a dead control."""
    names = {command.name for command in commands.COMMANDS}
    topics = {
        component.command_channel
        for component in ha_commands.components()
    }

    assert topics == {f'command/{name}' for name in names - _ENTITY_LESS}
