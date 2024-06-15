"""Setup the service."""

from __future__ import annotations

from datetime import UTC, datetime

from redux import FinishEvent

from ubo_app.store.main import dispatch, subscribe_event
from ubo_app.store.services.sensors import Sensor, SensorsReportReadingAction


def read_sensors(_: float | None = None) -> None:
    """Read the sensor."""
    import adafruit_pct2075
    import adafruit_veml7700
    import board

    i2c = board.I2C()
    temperature_sensor = adafruit_pct2075.PCT2075(i2c, address=0x48)
    temperature = temperature_sensor.temperature
    light_sensor = adafruit_veml7700.VEML7700(i2c, address=0x10)
    light = light_sensor.lux
    dispatch(
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


def init_service() -> None:
    """Initialize the service."""
    from kivy.clock import Clock

    clock_event = Clock.schedule_interval(read_sensors, 1)
    subscribe_event(FinishEvent, clock_event.cancel)
    read_sensors()
