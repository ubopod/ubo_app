"""Setup the service."""

from __future__ import annotations

import errno
from datetime import UTC, datetime
from typing import TYPE_CHECKING, TypeVar

import adafruit_pct2075
import adafruit_veml7700
import board
from redux import FinishEvent
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_fixed

from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.sensors import Sensor, SensorsReportReadingAction
from ubo_app.utils.eeprom import get_eeprom_data

if TYPE_CHECKING:
    from adafruit_rgb_display.rgb import busio

temperature_sensor: adafruit_pct2075.PCT2075 | None = None
light_sensor: adafruit_veml7700.VEML7700 | None = None


def read_sensors(_: float | None = None) -> None:
    """Read the sensor."""
    temperature = 0.0 if temperature_sensor is None else temperature_sensor.temperature
    light = 0.0 if light_sensor is None else light_sensor.lux
    store.dispatch(
        SensorsReportReadingAction(
            sensor=Sensor.TEMPERATURE,
            reading=temperature,
            timestamp=datetime.now(tz=UTC),
        ),
        SensorsReportReadingAction(
            sensor=Sensor.LIGHT,
            reading=light,
            timestamp=datetime.now(tz=UTC),
        ),
    )


T = TypeVar('T', bound=adafruit_pct2075.PCT2075 | adafruit_veml7700.VEML7700)


@retry(
    stop=stop_after_attempt(5),
    wait=wait_fixed(1),
    retry=retry_if_exception(
        lambda e: isinstance(e, OSError) and e.errno == errno.EIO,
    ),
)
def _initialize_device(cls: type[T], address: int, i2c: busio.I2C) -> T:
    """Initialize the I2C."""
    return cls(i2c, address)


def init_service() -> None:
    """Initialize the service."""
    from kivy.clock import Clock

    eeprom_data = get_eeprom_data()

    global temperature_sensor, light_sensor  # noqa: PLW0603

    i2c = board.I2C()
    try:
        if (
            eeprom_data is not None
            and 'temperature' in eeprom_data
            and eeprom_data['temperature'] is not None
            and eeprom_data['temperature']['model'].upper() == 'PCT2075'
        ):
            temperature_sensor = _initialize_device(
                adafruit_pct2075.PCT2075,
                int(eeprom_data['temperature']['bus_address'], 16),
                i2c,
            )
    except Exception:
        logger.exception('Error initializing temperature sensor')

    try:
        if (
            eeprom_data is not None
            and 'ambient' in eeprom_data
            and eeprom_data['ambient'] is not None
            and eeprom_data['ambient']['model'].upper() == 'VEML7700'
        ):
            light_sensor = _initialize_device(
                adafruit_veml7700.VEML7700,
                int(eeprom_data['ambient']['bus_address'], 16),
                i2c,
            )
    except Exception:
        logger.exception('Error initializing light sensor')

    clock_event = Clock.schedule_interval(read_sensors, 1)
    store.subscribe_event(FinishEvent, clock_event.cancel)
    read_sensors()
