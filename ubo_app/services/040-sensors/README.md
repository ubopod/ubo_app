# Sensors Service (`040-sensors`)

## Overview

The Sensors service owns the device's I2C bus. It reads the on-board sensors — a **PCT2075
temperature** sensor and a **VEML7700 ambient-light** sensor — and any **STEMMA QT sensor the user
plugs in**, on a one-second poll. Readings land in the `sensors` store slice, feed the status bar,
and are published to Home Assistant over MQTT discovery.

The user-facing goal: plug in a supported sensor, press **Settings → Hardware → Sensors → Refresh**,
and it appears on their Home Assistant dashboard. No config files, no code.

It loads in the `040-` tier (peripherals, alongside `040-rgb-ring`), after core/network so it can
register its reducer and status-bar hook once the store is ready.

See [`docs/architecture/UI_REDUX_ARCHITECTURE.md`](../../../docs/architecture/UI_REDUX_ARCHITECTURE.md)
for the store/action/event model.

## Supported sensors

Fifteen sensor models, 35 entities between them. The first two are **on-board** (resolved from the
HAT EEPROM, not the bus); the other thirteen are STEMMA QT / Qwiic parts the user plugs in and
discovers with **Settings → Hardware → Sensors → Refresh**.

| Sensor                      | Maker              | Address(es)            | Entities                                        |
| --------------------------- | ------------------ | ---------------------- | ----------------------------------------------- |
| PCT2075 Temperature ★       | NXP                | `0x48`–`0x4f`          | Temperature                                     |
| VEML7700 Ambient Light ★    | Vishay             | `0x10`                 | Illuminance                                     |
| AHT20 Temp/Humidity         | Aosong             | `0x38`                 | Temperature, Humidity                           |
| BME280 Environment          | Bosch              | `0x76`, `0x77`         | Temperature, Humidity, Pressure                 |
| BME680 Environment + Gas    | Bosch              | `0x76`, `0x77`         | Temperature, Humidity, Pressure, Gas Resistance |
| BMP388 Pressure             | Bosch              | `0x76`, `0x77`         | Pressure, Temperature, Altitude                 |
| SCD-40 CO₂                  | Sensirion          | `0x62`                 | CO₂, Temperature, Humidity                      |
| SGP40 VOC                   | Sensirion          | `0x59`                 | VOC Index                                       |
| ENS160 Air Quality          | ScioSense          | `0x53`, `0x52`         | eCO₂, TVOC, Air Quality Index, Data Validity    |
| SHT4x Temp/Humidity         | Sensirion          | `0x44`                 | Temperature, Humidity                           |
| BH1750 Ambient Light        | Rohm               | `0x23`, `0x5c`         | Illuminance                                     |
| MCP9808 Temperature         | Microchip          | `0x18`–`0x1f`          | Temperature                                     |
| PMSA003I Air Quality        | Plantower          | `0x12`                 | PM1.0, PM2.5, PM10                              |
| VL53L1X Distance            | STMicroelectronics | `0x29`                 | Distance                                        |
| APDS-9960 Proximity + Color | Avago              | `0x39`                 | Proximity, Red, Green, Blue, Clear              |

★ on-board.

This table is generated from [`registry.default.json`](registry.default.json), which is the source of
truth — if you add a sensor, update it here too. See [Adding a sensor](#adding-a-sensor).

## Files

| Path                    | Purpose                                                                          |
| ----------------------- | -------------------------------------------------------------------------------- |
| `ubo_handle.py`         | Registration (`service_id='sensors'`); registers the reducer, returns `init_service()`'s subscriptions. |
| `setup.py`              | Runtime: hydrate + activate devices, 1 s poll loop, persistence, status-bar dependency. |
| `reducer.py`            | Pure reducer: the device registry plus the two legacy status-bar fields.           |
| `registry.py`           | Sensor definitions: parsing, validation, loading.                                 |
| `registry.default.json` | The bundled sensor definitions. Data in form, executable in effect — see below.   |
| `drivers.py`            | Driver allowlist, instantiation (with retry), attribute reads.                    |
| `scan.py`               | I2C scanning, chip-ID probing, definition matching.                               |
| `menu.py`               | The Settings → Hardware → Sensors menu.                                           |
| `ha.py`                 | Pure `EntityDefinition` → `MqttComponent` translation for the MQTT bridge.        |

Store types: [`ubo_app/store/services/sensors.py`](../../store/services/sensors.py).

## How a sensor is recognized

1. **Refresh** dispatches `SensorsScanAction`; the reducer emits `SensorsScanEvent`.
2. `scan_and_match()` takes the I2C bus lock **once**, scans, and probes only those addresses where a
   candidate definition carries a probe. Blinka's `i2c.scan()` reads a byte from each address, but some
   sensors NAK a bare read and are invisible to it — Sensirion's SCD4x (`0x62`) and SGP40 (`0x59`) both
   do — so the scan is supplemented with an **address-only quick-write** probe (the same one `i2cdetect`
   uses) of *only* the addresses the registry claims. It writes no register pointer, and never touches a
   reserved or unclaimed address.
3. Precedence at an address: a definition whose chip-ID probe answers wins; failing that, a lone
   probe-less candidate wins; two probe-less candidates on one address is `AMBIGUOUS`.
4. Matched definitions get their (allowlisted) driver instantiated. Failures become `ERROR`;
   definitions naming a driver this build doesn't ship become `UNSUPPORTED`.
5. The on-board sensors are resolved from the **EEPROM**, not the bus — their model and address are
   already known — and are listed alongside the discovered ones.

### Reserved addresses — do not remove

`scan.RESERVED_ADDRESSES` (`0x1a` WM8960 audio codec, `0x50` HAT EEPROM, `0x58` AW9523 keypad
expander) is a **safety** mechanism, not an optimization. A probe *writes* a register pointer before
reading; a stray byte to the codec is a partial register write that can change audio configuration.
These addresses are never probed, and no registry definition may claim one (enforced by
`tests/store/test_sensors_registry.py`).

## Adding a sensor

1. Add its Adafruit driver to `pyproject.toml` (next to the other `adafruit-circuitpython-*` deps).
2. Add the module to `drivers.DRIVER_ALLOWLIST`. A definition can only load an allowlisted module —
   a JSON document must never be able to import arbitrary code.
3. Add a definition to `registry.default.json`.

If two definitions share an address, give at least one a `probe` (a chip-ID register read). The
tests will fail if two **probe-less** definitions collide, because the ambiguity-picker UI is
deliberately not built — no shipped sensor can trigger it.

The 0x76/0x77 pile-up is the worked example: **BME280, BME680 and BMP388 all answer there**, and
they are not even distinguished at the same register — the BME parts keep their chip ID at `0xd0`
(`0x60` / `0x61`), the BMP3xx at `0x00` (`0x50`). `tests/store/test_sensors_scan.py` drives the
shipped registry with fake chips to prove exactly one definition wins for each.

## The readings page (Settings → Hardware → Sensors → *a sensor*)

Selecting a sensor opens a **`readings` render view** — a label/value/unit table — not a submenu: a
menu row is a single line of text with nowhere to put a value or a unit. The widget is
`ubo_app/gui/ubo_gui_client/widgets/readings/`, registered in `GENERIC_RENDER_WIDGETS`.

It exists to answer "is this sensor actually being read?" at a glance, so a sensor that failed to
initialize opens a `status` page explaining why instead of an empty table, and an entity with no
reading shows `—` rather than `0` (a plausible-looking lie).

Two things make it work at 1 Hz:

- **`view_renderer._render_render_view` updates in place** when the props belong to the render
  stream already on screen (matched on `stream_id`). Without that it would rebuild the widget and
  replay the page-swap animation on every reading. This benefits every render kind, not just this one.
- **The widget rebuilds its rows only when `labels`/`units` change** (i.e. when a different sensor is
  opened). A new `values` list only re-texts the existing labels.

Names, units and display precision come from the **registry**, not the store: `SensorEntityReading`
carries only a key and a number.

Adafruit's drivers are not uniform, so a definition has five escape hatches:

| Field             | For                                                                     |
| ----------------- | ----------------------------------------------------------------------- |
| `init_kwargs`     | Extra constructor arguments.                                             |
| `post_init`       | Attributes assigned after construction — the VEML7700's integration time is a settable property, not a constructor argument. |
| `post_init_calls` | No-argument methods to invoke — the VL53L1X reports nothing until `start_ranging()`, nor the SCD-40 until `start_periodic_measurement()`. |
| `read_method`     | A method returning *all* values as a mapping — the PMSA003I's `read()`. Each entity's `attribute` is then a **key into that mapping**, not a property name, and the method is called **once per poll** (each call consumes a fresh frame from the sensor). An `attribute` the mapping does not carry falls back to a property read on the instance: the ENS160 buffers its measurements into `read_all_sensors()` but reports data validity from a live status register. |
| `read_primer`     | An attribute touched once **before** each poll to latch a fresh sample — the ENS160 presents data only after its `new_data_available` status flag is read; without it the data registers stay zero. |

An entity's `attribute` may also name a **no-argument method** rather than a property: the SGP40's
VOC index comes from `measure_index()`. Callables are invoked; properties are read.

A definition may also declare `min_read_interval`, in seconds — how long the sensor needs between
measurements, when that is *slower* than the poll loop. The SCD-40 sets it to `5`: it produces a
sample every five seconds, and each of its three entities is a property whose getter checks
`data_ready` over the bus, so polling it at 1 Hz spends fifteen round trips per sample it can
actually deliver. Inside the interval the poll serves that sensor's last reading from cache — the
same value the driver itself would return between measurements, minus the round trip. The default,
`0`, means "read it every tick", which is what a sensor at or above the poll rate wants; the SGP40
in particular **must** stay at 1 Hz, because Sensirion's VOC index algorithm is specified for
one-second sampling.

An entity may also override `value_template`, the Jinja expression Home Assistant renders. The default
reads the published key straight (`{{ value_json.<key> }}`); the ENS160's `validity` entity overrides
it, because its register reports 0-3 and nobody can read a bare `2` as "starting up". That sensor's
gas readings are meaningless until it has warmed up, and publishing the state beside them lets an
automation decide what to do about it — the pod does not withhold readings on the sensor's behalf.

The address is always passed to the constructor **by keyword**. Every driver names the parameter
`address`, but they do not agree on its *position*: `PM25_I2C` takes `reset_pin` second, so a
positional address would silently become a reset pin. A test asserts every bundled driver accepts
`address` as a keyword.

Note the entity `key` (used in the store, the menu, and the MQTT payload) is independent of the
driver `attribute`. The PMSA003I relies on this: Plantower's frame calls PM1.0 `pm10 standard` and
PM10 `pm100 standard` — a genuine trap, pinned by a test.

## The I²C worker thread

Every touch of the bus — opening it, scanning, driver construction, the 1 Hz poll — runs on **one
process-global daemon thread** (`ubo_app/utils/blocking_worker.py`, `WORKER =
BlockingWorker('sensors-i2c', …)`), never on the event loop. This is the service's most surprising
design element, and it is deliberate: cancelling an `await` cannot interrupt a running hardware
call, and service cleanup gives teardown a bounded grace period — so "wait for the old instance to
finish" is a promise that cannot be kept. Making the thread process-global per name means a
restarted service instance queues behind the old one's leftover work in the same FIFO queue,
which makes overlapping bus access impossible by construction.

`WORKER.run(...)` enforces a deadline, `I2C_CALL_TIMEOUT` (60 s) — long enough for a full scan in
which every driver exhausts its retries. A call that blows it marks the worker **wedged** and every
subsequent `run` fails fast (the poll loop absorbs this and keeps trying) until the overdue call
finally returns, at which point the thread has proven itself alive and the worker recovers.
`tests/store/test_blocking_worker.py` pins all of this.

### Per-sensor backoff

A device whose *every* entity failed to read is backed off before it is touched again — two
seconds, doubling per consecutive failure, capped at sixty, cleared by one successful read
(`BACKOFF_INITIAL_SECONDS` / `BACKOFF_MAX_SECONDS` in `drivers.py`). A single unreadable entity is
not a failure; a device that partly answers is still healthy.

This exists because a failed read usually is not a busy sensor. On this bus it means a slave is
wedged holding SDA low, which takes **every** device on the bus down with it — the keypad expander
and the audio codec included — and outlives a poll tick by minutes. A pod with six daisy-chained
sensors produced 537 `lost arbitration` and 628 `SDA stuck at low` aborts in one twelve-minute
episode, roughly two per second, because the 1 Hz loop kept retrying straight through it. Backing
off turns that storm into a handful of probes while the bus recovers.

Unlike the interval gate, a backed-off sensor reports `None` for every entity rather than its
cached reading: the all-null payload is deliberately dropped by the MQTT publish step, which is
what lets Home Assistant mark the sensor **unavailable** instead of holding a stale value at
`unknown` forever.

Note this is backoff, not electrical bus recovery. Clocking a wedged slave free means driving SCL
directly, and the kernel owns those pins while `i2c-1` is up.

## State

Slice: `state.sensors` — [`SensorsState`](../../store/services/sensors.py):

| Field           | Type                             | Meaning                                              |
| --------------- | -------------------------------- | ---------------------------------------------------- |
| `temperature`   | `SensorState`                    | **Legacy.** On-board temperature (°C), for the status bar. |
| `light`         | `SensorState`                    | **Legacy.** On-board ambient light (lux).            |
| `devices`       | `dict[str, SensorDeviceState]`   | Every known sensor, keyed by `{definition_id}_{address:#04x}`. |
| `is_scanning`   | `bool`                           | A bus scan is in flight.                             |

`temperature` / `light` are kept because the status bar
(`register_status_bar_dependency('sensors:temp', …)`) and the gRPC surface depend on them. The poll
loop dispatches the legacy `SensorsReportReadingAction`s **alongside** the per-device ones, and — as
before this became a device registry — reports `0.0` for an absent on-board sensor.

## Actions & Events

| Action                              | Result                                                              |
| ----------------------------------- | ------------------------------------------------------------------- |
| `SensorsScanAction`                 | Sets `is_scanning`, emits `SensorsScanEvent`.                        |
| `SensorsScanCompletedAction`        | **Replaces** the device registry (an unplugged sensor disappears). `devices=None` means the scan *failed*: stop scanning, keep the registry. |
| `SensorsReportDeviceReadingsAction` | Writes one device's entity readings. Unknown device id → no-op.      |
| `SensorsReportReadingAction`        | **Legacy.** Writes `temperature` / `light`.                          |

## Persistence

Only a device's **identity** is persisted (`sensors_devices` → a JSON list of
`{definition_id, address}` for non-built-ins), so sensors re-attach on boot without a re-scan.

`register_persistent_store` is an **autorun**: it rewrites `state.json` whenever its selector's
output changes. Readings must therefore never appear in `persistence_selector` — including them
would rewrite the file, on the SD card, once a second, forever. The same reasoning splits the menu
into two autoruns: the device list selects an identity-only projection, while only the open readings
page reacts to readings. Both invariants are pinned in `tests/store/test_sensors_menu.py`.

Two ways that file could be destroyed, both guarded (`tests/store/test_sensors_lifecycle.py`):

- An autorun fires on its **initial** value, so an ungated selector would write an empty list over
  the one the restore is still reading back in the worker thread. The autorun is registered
  unconditionally (and synchronously) in `init_service()`; the gate lives in the **selector**, which
  answers `None` — skipped by `register_persistent_store` — until `_arm_persistence()` marks that
  the store's device list reflects the hardware. See `persistence_selector`'s docstring for why
  registration must stay synchronous rather than waiting for the restore.
- A failed bus scan is **not** an empty bus. It reports `devices=None`, which keeps the registry
  rather than clearing it, persisting the loss and retiring every Home Assistant entity over a
  transient EIO.

## Home Assistant / MQTT

This service no longer owns an MQTT client. It is a *contributor* to the
[MQTT bridge](../050-mqtt/README.md), in two ways:

- **Entities** — `ha.py` translates each active device's `EntityDefinition`s into `MqttComponent`s,
  registered once via `register_mqtt_components('sensors', …)`. The bridge calls that provider
  whenever it announces, so this service never builds a discovery payload itself. A re-scan
  dispatches `MqttRequestAnnounceAction` so a newly plugged sensor is announced immediately rather
  than at the next reconnect.
- **Readings** — the 1 Hz poll loop dispatches `MqttPublishAction(channel=f'{device_id}/state', …)`.
  The channel is *relative*; the bridge owns the `ubo/{serial}/` prefix.

The resulting topics are unchanged: `ubo/{serial}/{device_id}/state` for readings, one retained
device-level discovery message for the entities.

Every entity is announced with `expire_after` (`ha.EXPIRE_AFTER`, 90 s): a sensor quiet for that
long goes `unavailable`. It is deliberately **above** `I2C_CALL_TIMEOUT` (60 s) — a re-scan holds
the hardware lock while every driver exhausts its retries, and a shorter expiry would flip every
entity to `unavailable` mid-scan, the exact false alarm it exists to avoid.

The user must add the MQTT integration in Home Assistant once (broker `mosquitto`, port 1883, no
credentials) — the composition's instructions text says so.

> **Note:** 1 Hz publishing is a deliberate choice. It is ~86k recorder rows per entity per day in
> Home Assistant's SQLite DB. The bridge's outbound queue is the place to throttle if that becomes a
> problem.

## Testing & Development Notes

| Test                                    | Tier        | What it covers                                                    |
| --------------------------------------- | ----------- | ----------------------------------------------------------------- |
| `tests/store/test_sensors_reducer.py`   | Unit        | The device-registry half of the reducer + the legacy status-bar fields. |
| `tests/store/test_sensors_registry.py`  | Unit        | Parsing/validation, driver allowlist, and invariants over the bundled registry: every driver, entity attribute and `post_init` attribute really exists, no reserved address is claimed, no unresolvable ambiguity. |
| `tests/store/test_sensors_scan.py`      | Unit        | Matching precedence; **reserved addresses are never probed**.      |
| `tests/store/test_sensors_drivers.py`   | Unit        | Reading entities off driver instances: `read_method`/`read_primer` shapes, per-entity failure isolation. |
| `tests/store/test_sensors_activation.py`| Unit        | `_apply`/`_activate` (driver reuse, UNSUPPORTED vs ERROR), `read_sensors`' legacy slots, and the poll loop surviving a failed poll. |
| `tests/store/test_sensors_menu.py`      | Unit        | Path matcher; readings don't churn the menu or the persistent store. |
| `tests/store/test_sensors_ha.py`        | Unit        | `EntityDefinition` → `MqttComponent` translation.                   |
| `tests/store/test_sensors_lifecycle.py` | Unit        | When the device list is persisted, and that a failed scan or restore does not erase it. |
| `tests/integration/test_services.py`    | Integration | The service registers and the store snapshot matches.              |

**Maintenance when you change this service:**

- **State shape** → regenerate store/window snapshots (never hand-edit), and run `uv run poe proto`
  (`ubo_app/rpc/_class_registry.py` is generated *and committed*).
- **Hardware-dependent:** off-device, `board` is faked and `get_eeprom_data()` is stubbed to return
  nothing (`setup_headless.py`), so there are no devices and readings are zeros — note that
  `UBO_FORCE_HARDWARE` does **not** change this. Real scanning, driver init, retry-on-`EIO`, and MQTT
  all need the device.
- **Entities exposed to Home Assistant** → update `ha.py` and `tests/store/test_sensors_ha.py`; the
  discovery payload itself is the bridge's concern.

To exercise on-device: start the Home Assistant composition, run
`mosquitto_sub -h 127.0.0.1 -t 'homeassistant/#' -t 'ubo/#' -v`, plug in a STEMMA QT sensor, and hit
Refresh. The sensor should appear under Home Assistant → Settings → Devices → MQTT; stopping
`ubo-app` should take its entities unavailable via the last-will message.

## Why the registry only ever loads from the image

A definition looks like data, but it names the class to construct, the arguments
to construct it with, attributes to set on the instance, methods to call, the
attribute a reading is read from, and the Jinja template Home Assistant renders.
`DRIVER_ALLOWLIST` covers the *module*; everything after the `getattr` is
whatever the document says.

So `load_registry` reads `registry.default.json` and nothing else. Supporting a
downloaded registry is not a matter of pointing the loader at another path — it
needs the trusted channel it would arrive on, and allowlisting exact driver
descriptors rather than modules. Until that exists, a second path would be
attack surface with no feature behind it.
