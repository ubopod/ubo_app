"""Utility functions for interacting with the EEPROM."""

import json
from pathlib import Path

from ubo_app.logging import logger
from ubo_app.utils import IS_RPI


def read_serial_number() -> str:
    """Read the serial number from the EEPROM."""
    if IS_RPI:
        try:
            eeprom_json_data = Path(
                '/proc/device-tree/hat/custom_0',
            ).read_text(encoding='utf-8')
            eeprom_data = json.loads(eeprom_json_data)
            return eeprom_data['serial_number']
        except Exception:
            logger.exception('Failed to read serial number')
    return '<not-available>'
