"""Expose this pod's infrared capability to Home Assistant.

Pure — no broker, no store reads — so the wire contract can be pinned by unit
tests. The service supplies the registered devices; this module decides how they
look to Home Assistant.

Two directions:

* **Send.** One `button` per already-registered device. Each carries its own
  ``protocol:scancode`` as ``payload_press``, so the bridge receives an
  identifier it can check against the registry rather than an arbitrary code to
  transmit. That is the whole reason there is no free-text "send any code"
  entity.
* **Receive.** One `event` entity. Home Assistant's event platform wants JSON
  carrying an ``event_type`` drawn from a declared list, so the declared types
  are the registered device names — an automation reacts to "Living Room TV
  Power", not to a hex scancode. Anything unrecognised arrives as ``unknown``
  with the raw code as attributes.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from ubo_app.store.services.mqtt import COMMAND_SEGMENT, MqttComponent

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_app.store.services.infrared import InfraredDevice

# The bridge's inbound command name. Matched by `050-mqtt/commands.py`; services
# cannot import each other, so the channel is the contract between them.
SEND_CHANNEL = f'{COMMAND_SEGMENT}/ir.send'
RECEIVED_CHANNEL = 'ir/received'

EVENT_COMPONENT_ID = 'ir_received'
UNKNOWN_EVENT_TYPE = 'unknown'


def code_of(device: InfraredDevice) -> str:
    """Identify a device by the code it sends — the registry's own key."""
    return f'{device.protocol}:{device.scancode}'


def _slug(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_')


def _component_id(device: InfraredDevice) -> str:
    """Derive the id from the name *and* the code.

    Neither alone is unique: names are explicitly non-unique, and two
    differently-named devices can share a ``protocol:scancode``. Only the pair
    distinguishes them — while a true duplicate still maps to the same id.
    """
    return f'ir_send_{_slug(device.name)}_{_slug(code_of(device))}'


def components(devices: Sequence[InfraredDevice]) -> list[MqttComponent]:
    """Describe the pod's infrared entities for Home Assistant.

    The event entity is offered even with no devices registered — a received
    code is still worth reporting as ``unknown``, and it is what lets an
    automation notice a remote the pod has never been taught.
    """
    event_types = tuple(dict.fromkeys(device.name for device in devices))

    return [
        MqttComponent(
            component_id=EVENT_COMPONENT_ID,
            platform='event',
            name='Infrared',
            state_channel=RECEIVED_CHANNEL,
            event_types=(*event_types, UNKNOWN_EVENT_TYPE),
        ),
        *(
            MqttComponent(
                component_id=_component_id(device),
                platform='button',
                name=device.name,
                command_channel=SEND_CHANNEL,
                # The identifier, not a raw code to transmit: the bridge looks
                # it up in the registry and refuses anything absent.
                payload_press=code_of(device),
                retain=False,
                qos=0,
            )
            for device in devices
        ),
    ]


def received_payload(
    protocol: str,
    scancode: str,
    devices: Sequence[InfraredDevice],
) -> str:
    """Render a received code as a Home Assistant event payload.

    ``event_type`` has to be one of the types declared in discovery, so an
    unregistered code reports as ``unknown`` rather than inventing a type Home
    Assistant would reject.
    """
    code = f'{protocol}:{scancode}'
    name = next(
        (device.name for device in devices if code_of(device) == code),
        UNKNOWN_EVENT_TYPE,
    )
    return json.dumps(
        {'event_type': name, 'protocol': protocol, 'scancode': scancode},
    )
