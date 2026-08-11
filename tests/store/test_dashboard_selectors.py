"""The whole-slice selectors the web dashboard subscribes to must be packable.

`SubscribeStore` packs each selector's result with `_pack_to_any`, which
refuses bare containers and raises on anything `build_message` cannot encode.
A raise there kills the stream for every selector in the request, not just the
offending one — which looks, on the client, like the dashboard never receiving
any readings at all.
"""

from __future__ import annotations

import pytest

from ubo_app.rpc.store_service import _pack_to_any
from ubo_app.store.services.docker import (
    DockerAppStatus,
    DockerItemHealth,
    DockerItemStatus,
    DockerServiceState,
)
from ubo_app.store.services.localization import (
    LocalizationState,
    LocationInfo,
    WeatherCondition,
)
from ubo_app.store.services.sensors import (
    SensorDeviceState,
    SensorEntityReading,
    SensorsState,
    SensorState,
    SensorStatus,
)
from ubo_app.store.services.system import SystemState

UBO_PREFIX = 'type.googleapis.com/ubo_bindings.ubo.v1.'


def _populated_sensors() -> SensorsState:
    return SensorsState(
        temperature=SensorState(value=21.5),
        light=SensorState(value=300.0),
        devices={
            'bme280_0x76': SensorDeviceState(
                id='bme280_0x76',
                definition_id='bme280',
                label='BME280 Environment',
                address=0x76,
                is_builtin=False,
                status=SensorStatus.ACTIVE,
                entities=(
                    SensorEntityReading(
                        key='temperature',
                        value=22.4,
                        name='Temperature',
                        unit='°C',
                        device_class='temperature',
                        precision=1,
                    ),
                    # A failed read, and an entity with no registry metadata.
                    SensorEntityReading(key='gas_resistance', value=None),
                ),
            ),
        },
    )


def _docker(apps: dict[str, DockerAppStatus] | None = None) -> DockerServiceState:
    """Build the slice without reading the real persistent store.

    Every other field on `DockerServiceState` defaults through
    `read_from_persistent_store`, and parametrize arguments are built at
    collection time — before any fixture could redirect that path. Passing them
    all explicitly keeps the test off the developer's own state file.
    """
    return DockerServiceState(
        usernames={},
        expose_to_lan={},
        zigbee_enabled=False,
        zigbee_adapter_by_id='',
        host_network_enabled=False,
        apps=apps or {},
    )


def _populated_docker() -> DockerServiceState:
    return _docker(
        {
            'home_assistant': DockerAppStatus(
                id='home_assistant',
                label='Home Assistant',
                icon='󰟐',
                status=DockerItemStatus.RUNNING,
                health=DockerItemHealth.CRASH_LOOPING,
            ),
            'pi_hole': DockerAppStatus(
                id='pi_hole',
                label='Pi-hole',
                icon='󰇖',
                status=DockerItemStatus.AVAILABLE,
            ),
        },
    )


@pytest.mark.parametrize(
    ('name', 'slice_'),
    [
        ('SystemState', SystemState()),
        (
            'SystemState',
            SystemState(
                cpu_percent=34.5,
                ram_percent=61.25,
                cpu_temperature_celsius=52.5,
                boot_time=1700000000.0,
                disk_total_bytes=32 * 1024**3,
                disk_used_bytes=8 * 1024**3,
                disk_percent=25.0,
                network_upload_bps=12345.0,
                network_download_bps=1234567.0,
            ),
        ),
        ('LocalizationState', LocalizationState()),
        (
            'LocalizationState',
            LocalizationState(
                location=LocationInfo(
                    latitude=52.52,
                    longitude=13.405,
                    city='Berlin',
                    country='Germany',
                ),
                weather=WeatherCondition(
                    symbol_code='partlycloudy_day',
                    temperature_celsius=21.0,
                    wind_speed_mps=3.0,
                ),
                clock='14:30',
                date='2026-08-08',
            ),
        ),
        ('SensorsState', SensorsState()),
        ('SensorsState', _populated_sensors()),
        ('DockerServiceState', _docker()),
        ('DockerServiceState', _populated_docker()),
    ],
    ids=[
        'system-empty',
        'system-populated',
        'localization-empty',
        'localization-populated',
        'sensors-empty',
        'sensors-populated',
        'docker-empty',
        'docker-populated',
    ],
)
def test_dashboard_slice_packs_to_a_ubo_message(name: str, slice_: object) -> None:
    """Each slice packs, and its type URL is the one the client dispatches on."""
    packed = _pack_to_any(slice_)  # pyright: ignore [reportArgumentType]

    assert packed.type_url == f'{UBO_PREFIX}{name}'
    assert packed.value != b''


def test_packed_system_state_round_trips_every_field() -> None:
    """The values survive the wire, under the names the bindings actually use.

    `betterproto`'s `snake_case` renames any field with a digit/letter
    boundary, so a name like `load_average_1m` silently stops matching the
    generated binding. Reading the values back catches that.
    """
    from ubo_bindings.ubo.v1 import SystemState as GRPCSystemState

    packed = _pack_to_any(
        SystemState(
            cpu_percent=34.5,
            ram_percent=61.25,
            cpu_temperature_celsius=52.5,
            load_average_1=0.31,
            load_average_5=0.28,
            load_average_15=0.25,
            boot_time=1700000000.0,
            disk_total_bytes=32 * 1024**3,
            disk_used_bytes=8 * 1024**3,
            disk_percent=25.0,
            network_upload_bps=12345.0,
            network_download_bps=1234567.0,
        ),
    )
    decoded = GRPCSystemState().parse(packed.value)

    assert decoded.cpu_percent == pytest.approx(34.5)
    assert decoded.cpu_temperature_celsius == pytest.approx(52.5)
    assert decoded.load_average_1 == pytest.approx(0.31)
    assert decoded.load_average_5 == pytest.approx(0.28)
    assert decoded.load_average_15 == pytest.approx(0.25)
    assert decoded.boot_time == pytest.approx(1700000000.0)
    assert decoded.disk_total_bytes == 32 * 1024**3
    assert decoded.disk_percent == pytest.approx(25.0)
    assert decoded.network_download_bps == pytest.approx(1234567.0)


def test_packed_localization_state_carries_the_clock_at_the_location() -> None:
    """The clock lives here, not in SystemState — it is the time *there*.

    The host timezone is never set from the detected location, so a clock
    computed from it can disagree with the time this same service speaks.
    """
    from ubo_bindings.ubo.v1 import LocalizationState as GRPCLocalizationState

    packed = _pack_to_any(
        LocalizationState(
            location=LocationInfo(latitude=52.52, longitude=13.405, city='Berlin'),
            clock='14:30',
            date='2026-08-08',
        ),
    )
    decoded = GRPCLocalizationState().parse(packed.value)

    assert decoded.clock == '14:30'
    assert decoded.date == '2026-08-08'
    assert decoded.location is not None
    assert decoded.location.city == 'Berlin'


def test_packed_sensors_state_keeps_device_readings_and_metadata() -> None:
    """A map of message values must survive — `devices` is `dict[str, ...]`."""
    from ubo_bindings.ubo.v1 import SensorsState as GRPCSensorsState

    packed = _pack_to_any(_populated_sensors())
    decoded = GRPCSensorsState().parse(packed.value)

    assert decoded.devices is not None
    device = decoded.devices.items['bme280_0x76']
    assert device.label == 'BME280 Environment'

    assert device.entities is not None
    readings = {entity.key: entity for entity in device.entities.items}
    assert readings['temperature'].value == pytest.approx(22.4)
    assert readings['temperature'].unit == '°C'
    assert readings['temperature'].device_class == 'temperature'
    assert readings['temperature'].precision == 1
    # A failed read stays absent rather than becoming a zero.
    assert readings['gas_resistance'].value is None


def test_packed_docker_service_state_keeps_per_app_status() -> None:
    """`apps` is a `dict[str, DockerAppStatus]` — a map of message values.

    This slice is what the Apps tile reads, and it is the reason the tile
    cannot simply select `state.docker`: the per-image states hang off the
    combine reducer as attributes with no proto counterpart.
    """
    from ubo_bindings.ubo.v1 import DockerItemHealth as GRPCDockerItemHealth
    from ubo_bindings.ubo.v1 import DockerItemStatus as GRPCDockerItemStatus
    from ubo_bindings.ubo.v1 import DockerServiceState as GRPCDockerServiceState

    packed = _pack_to_any(_populated_docker())
    decoded = GRPCDockerServiceState().parse(packed.value)

    assert decoded.apps is not None
    running = decoded.apps.items['home_assistant']
    assert running.label == 'Home Assistant'
    assert running.icon == '󰟐'
    assert running.status is GRPCDockerItemStatus.RUNNING
    # Health survives independently of the lifecycle status, so the client can
    # apply the same "health outranks status" precedence the menu tint does.
    assert running.health is GRPCDockerItemHealth.CRASH_LOOPING

    stopped = decoded.apps.items['pi_hole']
    assert stopped.status is GRPCDockerItemStatus.AVAILABLE
    assert stopped.health is GRPCDockerItemHealth.OK
