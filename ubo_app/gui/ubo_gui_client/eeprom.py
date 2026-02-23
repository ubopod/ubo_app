"""EEPROM data reader for display detection."""

from __future__ import annotations

import json
import logging
from functools import cache
from pathlib import Path
from typing import TypedDict

from ubo_gui_client.constants import IS_RPI

logger = logging.getLogger(__name__)


class Device(TypedDict):
    """Device information."""

    model: str
    bus_address: str
    test_result: bool


class LCDDevice(Device):
    """LCD device information."""


class EepromData(TypedDict):
    """EEPROM data."""

    serial_number: str
    lcd: LCDDevice | None
    version: str


UNAVAILABLE_SERIAL_NUMBER = '<not-available>'

EMPTY_EEPROM_DATA: EepromData = {
    'serial_number': UNAVAILABLE_SERIAL_NUMBER,
    'lcd': None,
    'version': '0.0.0',
}


@cache
def get_eeprom_data() -> EepromData:
    """Read the EEPROM data."""
    if not IS_RPI:
        return EMPTY_EEPROM_DATA
    try:
        eeprom_json_data = Path(
            '/proc/device-tree/hat/custom_0',
        ).read_text(encoding='utf-8')
        data = json.loads(eeprom_json_data)
    except Exception:
        logger.exception('Failed to read EEPROM data')
        return EMPTY_EEPROM_DATA
    else:
        if 'serial_number' not in data or 'version' not in data:
            logger.debug('Invalid EEPROM data')
            return EMPTY_EEPROM_DATA
        return {**EMPTY_EEPROM_DATA, **data}
