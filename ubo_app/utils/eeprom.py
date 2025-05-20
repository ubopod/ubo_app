"""Utility functions for interacting with the EEPROM."""

import json
from functools import cache
from pathlib import Path
from typing import TypedDict

from ubo_app.logger import logger
from ubo_app.utils import IS_RPI


class SoundTestReport(TypedDict):
    """Sound test report."""

    left: bool
    right: bool


class TemperatureTestReport(TypedDict):
    """Temperature test report."""

    degrees: float


class AmbientTestReport(TypedDict):
    """Ambient test report."""

    works: bool
    baseline: float
    reading: float
    delta: float


class KeypadTestReport(TypedDict):
    """Keypad test report."""

    L1: bool
    L2: bool
    L3: bool
    UP: bool
    DOWN: bool
    BACK: bool
    HOME: bool
    MIC: bool


class LCDTestReport(TypedDict):
    """LCD test report."""

    qrcode: bool
    green: bool
    red: bool
    blue: bool


class LEDTestReport(TypedDict):
    """LED test report."""

    green: bool
    red: bool
    blue: bool


class Device(TypedDict):
    """Device information."""

    model: str
    bus_address: str
    test_result: bool


class EepromDevice(Device):
    """EEPROM device information."""


class SpeakersDevice(Device):
    """Speakers device information."""

    test_report: SoundTestReport


class MicrophonesDevice(Device):
    """Microphones device information."""

    test_report: SoundTestReport


class TemperatureDevice(Device):
    """Temperature device information."""

    test_report: TemperatureTestReport


class AmbientDevice(Device):
    """Ambient device information."""

    test_report: AmbientTestReport


class KeypadDevice(Device):
    """Keypad device information."""

    test_report: KeypadTestReport


class LCDDevice(Device):
    """LCD device information."""

    test_report: LCDTestReport


class LEDDevice(Device):
    """LED device information."""

    test_report: LEDTestReport


class InfraredDevice(Device):
    """Infrared device information."""

    test_result: bool


class I2CBus(TypedDict):
    """I2C bus information."""

    num_devices: int
    scanned_addressed: list[str]
    status: str


class EepromData(TypedDict):
    """EEPROM data."""

    serial_number: str
    eeprom: EepromDevice | None
    speakers: SpeakersDevice | None
    microphones: MicrophonesDevice | None
    temperature: TemperatureDevice | None
    ambient: AmbientDevice | None
    keypad: KeypadDevice | None
    i2c_bus: I2CBus | None
    lcd: LCDDevice | None
    led: LEDDevice | None
    infrared: InfraredDevice | None
    version: str
    timedate: str | None
    test_result: bool | None


EMPTY_EEPROM_DATA: EepromData = {
    'serial_number': '<not-available>',
    'eeprom': None,
    'speakers': None,
    'microphones': None,
    'temperature': None,
    'ambient': None,
    'keypad': None,
    'i2c_bus': None,
    'lcd': None,
    'led': None,
    'infrared': None,
    'version': '0.0.0',
    'timedate': None,
    'test_result': None,
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
            return EMPTY_EEPROM_DATA
        eeprom_data: EepromData = data
        return {**EMPTY_EEPROM_DATA, **eeprom_data}


def read_serial_number() -> str | None:
    """Read the serial number from the EEPROM."""
    data = get_eeprom_data()
    return data['serial_number']
