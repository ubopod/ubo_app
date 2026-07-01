# Sensors Service (`040-sensors`)

## Overview

The Sensors service reads the device's on-board I2C sensors — a **PCT2075 temperature** sensor and a
**VEML7700 ambient-light** sensor — on a one-second poll and publishes their latest readings into the
`sensors` store slice. It also registers a status-bar dependency so the current temperature can be
shown in the UI.

It loads in the `040-` tier (peripherals, alongside `040-rgb-ring`), after core/network so it can
register its reducer and status-bar hook once the store is ready.

See [`docs/architecture/UI_REDUX_ARCHITECTURE.md`](../../../docs/architecture/UI_REDUX_ARCHITECTURE.md)
for the store/action/event model.

## Files

| Path            | Purpose                                                                          |
| --------------- | ------------------------------------------------------------------------------- |
| `ubo_handle.py` | Registration (`service_id='sensors'`); registers the reducer, returns `init_service()`'s subscriptions. |
| `setup.py`      | Runtime: EEPROM-gated I2C device init (with retry), 1 s poll loop, status-bar dependency. |
| `reducer.py`    | Pure reducer: folds `SensorsReportReadingAction` into per-sensor `SensorState`. |

Store types: [`ubo_app/store/services/sensors.py`](../../store/services/sensors.py).

## State

Slice: `state.sensors` — [`SensorsState`](../../store/services/sensors.py):

| Field         | Type          | Meaning                                        |
| ------------- | ------------- | --------------------------------------------- |
| `temperature` | `SensorState` | Latest temperature reading (°C).              |
| `light`       | `SensorState` | Latest ambient-light reading (lux).           |

`SensorState` wraps a single `value: float | None` (`None` until the first read or when a sensor is
absent). The `Sensor` enum (`TEMPERATURE`, `LIGHT`) selects which field a reading targets.

## Actions & Events

The reducer is a pure state-mapper — no events, no cross-service actions.

| Action                        | Reducer result                                                        |
| ----------------------------- | -------------------------------------------------------------------- |
| `SensorsReportReadingAction`  | Matched on `sensor`: writes `SensorState(value=reading)` into `temperature` or `light`. |

`SensorsReportReadingAction` also carries a `timestamp: float` (dispatched by the poller; not stored).
On `InitAction` the reducer seeds a default `SensorsState()` (both sensors `value=None`).

## Runtime & Setup

`init_service()` (`setup.py:71`) registers the status-bar dependency, initializes whatever sensors the
EEPROM advertises, does one immediate read, then starts a poll loop and returns a `Subscriptions`
list for teardown:

```python
unregister_temp = register_status_bar_dependency(
    'sensors:temp',
    lambda s: s.sensors.temperature.value if s.sensors.temperature else None,
)
...
end_event = asyncio.Event()
create_task(_monitor_sensors(end_event))
return [end_event.set, unregister_temp]
```

- **EEPROM-gated init:** each sensor is created only if the EEPROM lists a matching model+address
  (`temperature` → `PCT2075`, `ambient` → `VEML7700`). Missing/mismatched hardware leaves the
  module-level `temperature_sensor` / `light_sensor` as `None`, and `read_sensors()` reports `0.0`
  for that channel.
- **Resilient device init:** `_initialize_device()` (`setup.py:60`) is wrapped in `tenacity` retry —
  5 attempts, 1 s apart, but **only** for `OSError`/`EIO` (transient I2C bus errors). Any other init
  failure is logged via `report_service_error()` and the service continues without that sensor.
- **Poll loop:** `_monitor_sensors()` (`setup.py:65`) calls `read_sensors()` every second;
  `read_sensors()` dispatches two `SensorsReportReadingAction`s (temperature + light) in one
  `store.dispatch` call.
- **Teardown:** the returned `[end_event.set, unregister_temp]` stops the loop and removes the
  status-bar dependency.

## User Interface

No settings entry or menu. The service's only UI surface is the **status-bar temperature dependency**
registered via `register_status_bar_dependency('sensors:temp', …)`, which lets the status bar render
the current temperature. Rendering itself is owned by the view layer, not this service.

## System / Hardware Integration

- **I2C via CircuitPython** (`board.I2C()`) with Adafruit drivers `adafruit_pct2075` and
  `adafruit_veml7700`. The VEML7700 is additionally configured with a 50 ms integration time
  (`ALS_50MS`).
- **EEPROM discovery:** `get_eeprom_data()` supplies each sensor's model and hex `bus_address`
  (parsed with `int(addr, 16)`), so the same code adapts to boards that populate only some sensors.
- Read-only hardware access; no `send_command`/privileged operations.

## Cross-Service Interactions

None at the action level — the service neither dispatches to nor reads other services' slices. Its
outputs are the `sensors` slice and the `sensors:temp` status-bar dependency, consumed by the view
layer / any status-bar renderer.

## Configuration

No env vars or secrets. Behavior is driven by EEPROM entries (`temperature`/`ambient` model +
`bus_address`); the poll interval (1 s) and retry policy (5 × 1 s on `EIO`) are inline in `setup.py`.

## Testing & Development Notes

Related tests:

| Test                                  | Tier        | What it covers                                                       |
| ------------------------------------- | ----------- | ------------------------------------------------------------------- |
| `tests/integration/test_services.py`  | Integration | Asserts the `sensors` service registers and the store snapshot matches. |

> There is currently **no dedicated unit test** for the sensors reducer. It is pure and trivial to
> cover — dispatch `SensorsReportReadingAction(sensor=Sensor.TEMPERATURE, reading=…)` /
> `Sensor.LIGHT` and assert the resulting `SensorsState` fields. Adding
> `tests/store/test_sensors_reducer.py` is a good first contribution if you touch this service.

**Maintenance when you change this service:**

- **State shape** (`SensorsState` / `SensorState`) → regenerate store/window snapshots (never
  hand-edit); this updates the `test_services.py` fixture and the status-bar rendering.
- **Reducer branches** (new sensor / new `Sensor` member) → cover the branch with a small
  `tests/store` pure-reducer unit test rather than an E2E flow.
- **Hardware-dependent:** the I2C drivers require real hardware; on a dev host `board.I2C()` /
  the Adafruit sensors are unavailable or mocked, so `read_sensors()` reports zeros. Verify real
  readings and the retry-on-`EIO` behavior on-device.

To exercise manually: on-device, confirm the status bar shows a plausible temperature and that it
tracks changes (e.g. warming the board), and check `state.sensors` updates once per second.
