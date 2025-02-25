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

if TYPE_CHECKING:
    from adafruit_rgb_display.rgb import busio

temperature_sensor: adafruit_pct2075.PCT2075
light_sensor: adafruit_veml7700.VEML7700


def read_sensors(_: float | None = None) -> None:
    """Read the sensor."""
    temperature = temperature_sensor.temperature
    light = light_sensor.lux
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

    global temperature_sensor, light_sensor  # noqa: PLW0603

    i2c = board.I2C()
    try:
        temperature_sensor = _initialize_device(adafruit_pct2075.PCT2075, 0x48, i2c)
    except Exception:
        logger.exception('Error initializing temperature sensor')

    try:
        light_sensor = _initialize_device(adafruit_veml7700.VEML7700, 0x10, i2c)
    except Exception:
        logger.exception('Error initializing light sensor')

    clock_event = Clock.schedule_interval(read_sensors, 1)
    store.subscribe_event(FinishEvent, clock_event.cancel)
    read_sensors()
