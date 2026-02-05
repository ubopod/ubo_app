# ruff: noqa: D100, D103
"""Coordinator detection and probing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import serial.tools.list_ports
from zha.application.const import RadioType

from ubo_app.logger import logger

if TYPE_CHECKING:
    from serial.tools.list_ports_common import ListPortInfo

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
        'path': port,
        'baudrate': baudrate,
        'flow_control': 'hardware',
    }

    try:
        result = await asyncio.wait_for(
            controller_cls.probe(device_config),
            timeout=5.0,
        )
        return bool(result)
    except TimeoutError:
        logger.debug(
            'Timeout probing %s with %s at %d',
            port,
            radio_type.name,
            baudrate,
        )
        return False
    except Exception as exc:
        logger.debug(
            'Error probing %s with %s at %d: %s',
            port,
            radio_type.name,
            baudrate,
            exc,
        )
        return False


async def probe_port(port_info: ListPortInfo) -> DetectedCoordinator | None:
    """Probe a single port for all radio types and baudrates."""
    port = port_info.device
    description = port_info.description or 'Unknown device'

    logger.debug('Probing port %s (%s)', port, description)

    for radio_type in RadioType:
        for baudrate in PROBE_BAUDRATES:
            logger.verbose(
                'Trying radio probe',
                extra={
                    'port': port,
                    'radio_type': radio_type.name,
                    'baudrate': baudrate,
                },
            )
            if await _probe_port_with_radio(port, radio_type, baudrate):
                logger.info(
                    'Detected %s coordinator at %s (%d baud)',
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
        logger.info('No serial ports found')
        return []

    logger.info('Found %d serial port(s) to probe', len(ports))

    coordinators: list[DetectedCoordinator] = []

    # Probe ports sequentially to avoid resource conflicts
    for port_info in ports:
        result = await probe_port(port_info)
        if result:
            coordinators.append(result)

    return coordinators
