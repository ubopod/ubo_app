"""Describe the inbound commands as Home Assistant entities.

Pure: no broker, no store reads, so the wire contract can be pinned by unit
tests. Which commands are *offered* is decided by the caller.

Not every command gets an entity. `ring.color` takes three channels, which no
single stock platform expresses without a `light` — and a proper `light` needs
`schema: json` (whose payload is HA's own `state`/`brightness`/`color` shape,
not raw RGB) plus state reporting, which `RgbRingState` cannot provide: it holds
only `is_busy`. So colour stays an automation-driven topic and the rest are
entities.
"""

from __future__ import annotations

from ubo_app.store.services.mqtt import COMMAND_SEGMENT, MqttComponent
from ubo_app.store.services.notifications import Chime

# One entity per command that a stock Home Assistant platform can express.
# Keyed by the command name in `commands.COMMANDS`; the channel is derived, so
# a rename cannot leave the entity pointing at a dead topic.
_ENTITIES: tuple[tuple[str, dict[str, object]], ...] = (
    (
        'notify',
        {
            'platform': 'notify',
            'name': 'Notification',
            # No `command_template`: the notify platform publishes the raw
            # message text, and the discovery docs do not say which variables a
            # template would get. A wrong guess yields an entity that silently
            # never works.
        },
    ),
    (
        'speak',
        {
            'platform': 'notify',
            'name': 'Speak',
            # A second `notify` entity rather than a `text` one: the platform
            # publishes the raw message text, which is exactly what there is to
            # say, and a `text` entity is stateful — with no state topic to
            # report back on it renders as `unknown`. Same reason as `notify`
            # for declaring no `command_template`.
        },
    ),
    (
        'chime',
        {
            'platform': 'select',
            'name': 'Chime',
            # `options` is required for a select.
            'options': tuple(chime.value for chime in Chime),
        },
    ),
    (
        'ring.brightness',
        {
            'platform': 'number',
            'name': 'Ring Brightness',
            # Mandatory. Home Assistant defaults a number to min 1, max 100,
            # step 1 — an unset 0..1 brightness would render as a 1-100 integer
            # slider and publish values the pod rejects.
            'min_value': 0,
            'max_value': 1,
            'step': 0.05,
            'mode': 'slider',
        },
    ),
    (
        'ring.off',
        {
            'platform': 'button',
            'name': 'Ring Off',
            'payload_press': 'PRESS',
        },
    ),
)


def _component_id(name: str) -> str:
    return f'cmd_{name.replace(".", "_")}'


def components() -> list[MqttComponent]:
    """Describe every inbound command that a stock HA platform can express.

    Unconditional: the bridge drops commandable entities globally while Home
    Assistant control is off, so a contributor never has to check consent — and
    cannot forget to.
    """
    return [
        MqttComponent(
            component_id=_component_id(name),
            command_channel=f'{COMMAND_SEGMENT}/{name}',
            # Commands must never be retained: a retained one replays on every
            # reconnect. The bridge refuses retained inbound messages too, so
            # this is the near half of a belt-and-braces pair.
            retain=False,
            qos=0,
            **fields,  # pyright: ignore [reportArgumentType]
        )
        for name, fields in _ENTITIES
    ]
