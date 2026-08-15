"""Topic layout for the pod's MQTT namespace.

Everything the pod publishes lives under ``ubo/<serial>/``. Producers hand the
bridge a *relative* channel and this module renders the absolute topic, so no
other service needs to know the pod's identity.

No broker, no store. `device_serial` is the one impurity: it reads the HAT
EEPROM serial (falling back to the pod-id file); everything else is pure.
"""

from __future__ import annotations

import re

from constants import DISCOVERY_PREFIX

from ubo_app.store.services.mqtt import COMMAND_SEGMENT
from ubo_app.utils.eeprom import read_serial_number
from ubo_app.utils.pod_id import get_pod_id


def sanitize(value: str) -> str:
    """Reduce a value to the characters that are safe in a topic segment."""
    return re.sub(r'[^a-z0-9_]', '_', value.lower())


def device_serial() -> str:
    """Return a stable id for this pod, used in topics and entity unique-ids."""
    return sanitize(read_serial_number() or get_pod_id(with_default=True))


def availability_topic(serial: str) -> str:
    """Topic carrying `online`/`offline` for the whole pod."""
    return f'ubo/{serial}/availability'


def channel_topic(serial: str, channel: str) -> str:
    """Render a producer's relative channel into an absolute topic."""
    return f'ubo/{serial}/{channel}'


def discovery_topic(serial: str) -> str:
    """Topic carrying the retained device-level discovery payload."""
    return f'{DISCOVERY_PREFIX}/device/ubo_{serial}/config'


def command_topic(serial: str, name: str) -> str:
    """Topic Home Assistant publishes one command to."""
    return f'ubo/{serial}/{COMMAND_SEGMENT}/{name}'


def command_subscription(serial: str) -> str:
    """Filter covering every inbound command for this pod.

    Deliberately a dedicated `command/` sub-namespace rather than
    ``ubo/<serial>/#`` — that would make the pod receive back every reading it
    publishes, which matters more on a shared LAN broker carrying other
    devices' traffic.
    """
    return f'ubo/{serial}/{COMMAND_SEGMENT}/#'


def parse_command_name(serial: str, topic: str) -> str | None:
    """Extract a command name from an inbound topic, or None if it is not ours.

    An exact prefix comparison rather than wildcard matching, so a topic that
    merely *looks* similar cannot reach the command table. The name has to be a
    single plain segment: anything with a separator, a wildcard or a traversal
    is rejected rather than normalized.
    """
    prefix = f'ubo/{serial}/{COMMAND_SEGMENT}/'
    if not topic.startswith(prefix):
        return None
    name = topic[len(prefix) :]
    if not name or '/' in name or '+' in name or '#' in name or '..' in name:
        return None
    return name


def is_relative(channel: str) -> bool:
    """Whether a producer-supplied channel is safe to publish.

    The bridge owns the ``ubo/<serial>/`` prefix; a producer that tries to
    escape it — with a leading slash, a parent traversal, or a wildcard — is
    rejected rather than silently rewritten.
    """
    return bool(channel) and not (
        channel.startswith('/')
        or channel.endswith('/')
        or '//' in channel
        or '+' in channel
        or '#' in channel
        or '..' in channel
    )
