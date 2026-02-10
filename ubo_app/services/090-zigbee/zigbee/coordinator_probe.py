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

# Common baudrates to try when probing (115200 is most common, try it first)
PROBE_BAUDRATES = [115200, 57600, 38400]

# Probe timeout in seconds (reduced for faster detection)
PROBE_TIMEOUT = 2.0

# Maximum number of detection attempts before giving up
MAX_DETECTION_ATTEMPTS = 3
LAST_ATTEMPT_INDEX = MAX_DETECTION_ATTEMPTS - 1


@dataclass
class DetectedCoordinator:
    """Represents a detected Zigbee coordinator."""

    port: str
    description: str
    radio_type: RadioType
    baudrate: int


def _is_likely_zigbee_port(port_info: ListPortInfo) -> bool:
    """Check if a port is likely to be a Zigbee coordinator."""
    device = port_info.device.lower()
    description = (port_info.description or '').lower()

    # Skip Bluetooth ports
    if 'bluetooth' in device or 'bluetooth' in description:
        return False

    # Skip debug/console ports
    if 'debug' in device or 'console' in device:
        return False

    # Look for USB serial devices (common Zigbee coordinator patterns)
    usb_patterns = ['usbserial', 'usbmodem', 'ttyusb', 'ttyacm', 'com']
    if any(pattern in device for pattern in usb_patterns):
        return True

    # Check for known Zigbee coordinator descriptions
    zigbee_patterns = [
        'skyconnect', 'conbee', 'zigbee', 'coordinator', 'sonoff', 'cc2531',
    ]
    if any(pattern in description for pattern in zigbee_patterns):
        return True

    # Default: probe USB devices
    return 'usb' in device or port_info.vid is not None


def _get_serial_ports() -> list[ListPortInfo]:
    """Get available serial ports that are likely Zigbee coordinators."""
    all_ports = list(serial.tools.list_ports.comports())
    filtered = [p for p in all_ports if _is_likely_zigbee_port(p)]

    if len(filtered) < len(all_ports):
        logger.debug(
            'Filtered ports: %d -> %d (skipped non-USB/Bluetooth)',
            len(all_ports),
            len(filtered),
        )

    return filtered


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
            timeout=PROBE_TIMEOUT,
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
    except Exception as exc:  # noqa: BLE001
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

    Includes retry logic to handle transient failures during device initialization.
    """
    # Brief delay to ensure serial ports are ready after system boot
    await asyncio.sleep(0.5)

    for attempt in range(MAX_DETECTION_ATTEMPTS):
        ports = _get_serial_ports()

        if not ports:
            logger.info(
                'No serial ports found (attempt %d/%d)',
                attempt + 1,
                MAX_DETECTION_ATTEMPTS,
            )
            if attempt < LAST_ATTEMPT_INDEX:
                await asyncio.sleep(1.0)
                continue
            return []

        logger.info(
            'Found %d serial port(s) to probe (attempt %d/%d)',
            len(ports),
            attempt + 1,
            MAX_DETECTION_ATTEMPTS,
        )

        coordinators: list[DetectedCoordinator] = []

        # Probe ports sequentially to avoid resource conflicts
        for port_info in ports:
            result = await probe_port(port_info)
            if result:
                coordinators.append(result)

        if coordinators:
            return coordinators

        if attempt < LAST_ATTEMPT_INDEX:
            logger.info('No coordinators found, retrying in 1s...')
            await asyncio.sleep(1.0)

    return []
