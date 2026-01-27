"""Coordinator detection and probing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING

import serial.tools.list_ports

from zha.application.const import RadioType

if TYPE_CHECKING:
    from serial.tools.list_ports_common import ListPortInfo

_LOGGER = logging.getLogger(__name__)

# Common baudrates to try when probing
PROBE_BAUDRATES = [115200, 57600, 38400]


@dataclass
class DetectedCoordinator:
    """Represents a detected Zigbee coordinator."""

    port: str
    description: str
    radio_type: RadioType
    baudrate: int


def _get_serial_ports() -> list[ListPortInfo]:
    """Get available serial ports."""
    return list(serial.tools.list_ports.comports())


async def _probe_port_with_radio(
    port: str,
    radio_type: RadioType,
    baudrate: int,
) -> bool:
    """Try to probe a port with a specific radio type and baudrate."""
    controller_cls = radio_type.controller

    device_config = {
        "path": port,
        "baudrate": baudrate,
        "flow_control": "hardware",
    }

    try:
        result = await asyncio.wait_for(
            controller_cls.probe(device_config),
            timeout=5.0,
        )
        return bool(result)
    except TimeoutError:
        _LOGGER.debug(
            "Timeout probing %s with %s at %d",
            port,
            radio_type.name,
            baudrate,
        )
        return False
    except Exception as exc:
        _LOGGER.debug(
            "Error probing %s with %s at %d: %s",
            port,
            radio_type.name,
            baudrate,
            exc,
        )
        return False


async def probe_port(port_info: ListPortInfo) -> DetectedCoordinator | None:
    """Probe a single port for all radio types and baudrates."""
    port = port_info.device
    description = port_info.description or "Unknown device"

    _LOGGER.debug("Probing port %s (%s)", port, description)

    for radio_type in RadioType:
        for baudrate in PROBE_BAUDRATES:
            _LOGGER.debug(
                "Trying %s with %s at %d baud",
                port,
                radio_type.name,
                baudrate,
            )
            if await _probe_port_with_radio(port, radio_type, baudrate):
                _LOGGER.info(
                    "Detected %s coordinator at %s (%d baud)",
                    radio_type.pretty_name,
                    port,
                    baudrate,
                )
                return DetectedCoordinator(
                    port=port,
                    description=description,
                    radio_type=radio_type,
                    baudrate=baudrate,
                )

    return None


async def discover_coordinators() -> list[DetectedCoordinator]:
    """Discover all available Zigbee coordinators.

    Enumerates serial ports and tries each RadioType's controller probe() method.
    Returns a list of successfully detected coordinators.
    """
    ports = _get_serial_ports()

    if not ports:
        _LOGGER.info("No serial ports found")
        return []

    _LOGGER.info("Found %d serial port(s) to probe", len(ports))

    coordinators: list[DetectedCoordinator] = []

    # Probe ports sequentially to avoid resource conflicts
    for port_info in ports:
        result = await probe_port(port_info)
        if result:
            coordinators.append(result)

    return coordinators


async def probe_specific_port(
    port: str,
    radio_type: RadioType | None = None,
    baudrate: int | None = None,
) -> DetectedCoordinator | None:
    """Probe a specific port with optional radio type and baudrate hints.

    If radio_type and baudrate are provided, only that combination is tried.
    Otherwise, all combinations are attempted.
    """
    # Get port description if available
    ports = _get_serial_ports()
    port_info = next((p for p in ports if p.device == port), None)
    description = port_info.description if port_info else "Unknown device"

    if radio_type and baudrate:
        # Try specific combination
        if await _probe_port_with_radio(port, radio_type, baudrate):
            return DetectedCoordinator(
                port=port,
                description=description,
                radio_type=radio_type,
                baudrate=baudrate,
            )
        return None

    # Try all combinations
    radio_types = [radio_type] if radio_type else list(RadioType)
    baudrates = [baudrate] if baudrate else PROBE_BAUDRATES

    for rt in radio_types:
        for br in baudrates:
            if await _probe_port_with_radio(port, rt, br):
                return DetectedCoordinator(
                    port=port,
                    description=description,
                    radio_type=rt,
                    baudrate=br,
                )

    return None
