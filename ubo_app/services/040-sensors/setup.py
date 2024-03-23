"""Setup the service."""

from __future__ import annotations

from datetime import datetime, timezone

from ubo_app.store import dispatch
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
            timestamp=datetime.now(tz=timezone.utc),
        ),
        SensorsReportReadingAction(
            sensor=Sensor.LIGHT,
            reading=light,
            timestamp=datetime.now(tz=timezone.utc),
        ),
    )


def init_service() -> None:
    """Initialize the service."""
    from kivy.clock import Clock

    Clock.schedule_interval(read_sensors, 1)
    read_sensors()
