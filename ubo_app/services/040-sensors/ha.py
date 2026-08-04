"""Translate sensor definitions into Home Assistant entities.

The registry describes sensors in this service's own vocabulary
(`EntityDefinition`); the MQTT bridge speaks Home Assistant's
(`MqttComponent`). This module is the seam between them, and it is pure so the
mapping can be tested without a broker or a bus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.store.services.mqtt import MqttComponent
from ubo_app.store.services.sensors import SensorStatus

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from registry import SensorDefinition

    from ubo_app.store.services.sensors import SensorDeviceState

# A reading arrives every second, so a sensor quiet for this long is genuinely
# gone. It has to clear the worst case for a *healthy* pause, though: a re-scan
# holds the hardware lock while every driver exhausts its retries — up to
# `setup.I2C_CALL_TIMEOUT` (60 s) — and an expiry inside that window would flip
# every entity to `unavailable` mid-scan, the exact false alarm this exists to
# avoid. Belt and braces alongside the bridge's last-will message, which covers
# a clean disconnect but not a severed link.
EXPIRE_AFTER = 90


def state_channel(device_id: str) -> str:
    """Relative channel a device's readings are published on."""
    return f'{device_id}/state'


def components(
    devices: Sequence[SensorDeviceState],
    definitions: Mapping[str, SensorDefinition],
) -> list[MqttComponent]:
    """Describe every active sensor's entities for Home Assistant.

    A device that failed to initialize has nothing to report, and a device
    whose definition vanished from under it (a registry update) is skipped
    rather than announced half-described.
    """
    result: list[MqttComponent] = []

    for device in devices:
        if device.status is not SensorStatus.ACTIVE:
            continue
        definition = definitions.get(device.definition_id)
        if definition is None:
            continue

        result.extend(
            MqttComponent(
                component_id=f'{device.id}_{entity.key}',
                platform='sensor',
                name=f'{device.label} {entity.name}',
                state_channel=state_channel(device.id),
                # Reads the entity *key*, which is what the poll loop
                # publishes — not the driver's own attribute name. A definition
                # may override it for a reading that is a code rather than a
                # measurement.
                value_template=entity.value_template
                or f'{{{{ value_json.{entity.key} }}}}',
                expire_after=EXPIRE_AFTER,
                device_class=entity.device_class,
                unit_of_measurement=entity.unit_of_measurement,
                state_class=entity.state_class,
                suggested_display_precision=entity.suggested_display_precision,
            )
            for entity in definition.entities
        )

    return result
