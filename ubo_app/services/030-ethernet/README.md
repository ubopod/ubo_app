# Ethernet Service (`030-ethernet`)

## Overview

The Ethernet service is a thin **observability** layer over the device's wired network
interface: it watches the ethernet device via NetworkManager (D-Bus) and publishes a single
status-bar icon reflecting its link state. It owns no Redux slice, no menu, and no privileged
control — it only reads NetworkManager and pushes an icon.

It loads in the `030-` (network) tier alongside `030-wifi` and `030-ip`, after display and core
services so it can register a status icon and reflect connectivity as soon as the network stack is
up.

See [`docs/architecture/UI_REDUX_ARCHITECTURE.md`](../../../docs/architecture/UI_REDUX_ARCHITECTURE.md)
for the store/action/event model this service plugs into.

## Files

| Path                  | Purpose                                                                    |
| --------------------- | ------------------------------------------------------------------------- |
| `ubo_handle.py`       | Registration (`service_id='ethernet'`); calls `init_service()` (no reducer). |
| `setup.py`            | Runtime: D-Bus listener + debounced status-icon autopublish.              |
| `constants.py`        | Status-icon id/priority (`ethernet:state`, priority `-13`).               |
| `ethernet_manager.py` | NetworkManager (D-Bus) client: find the ethernet device, map its state to `NetState`. |

Store types: [`ubo_app/store/services/ethernet.py`](../../store/services/ethernet.py) — this module
only defines the shared `NetState` enum; the service has **no state slice of its own**.

## State

None. The service registers no reducer and holds no Redux slice — its only output is a status icon
dispatched via `StatusIconsRegisterAction`.

The store module does define the `NetState` enum (`CONNECTED`, `DISCONNECTED`, `PENDING`,
`NEEDS_ATTENTION`, `UNKNOWN`) at
[`ubo_app/store/services/ethernet.py:7`](../../store/services/ethernet.py), which is **shared with
`030-wifi`** (imported by `wifi_manager.py`, `wifi/reducer.py`, `wifi/pages/main.py`, and
`store/services/wifi.py`). Note that `030-ip` does *not* use `NetState` — it tracks reachability as
a plain `is_connected` bool.

## Actions & Events

None. The service dispatches only the core `StatusIconsRegisterAction`; it defines no actions or
events of its own.

## Runtime & Setup

`init_service()` (`setup.py:44`) is synchronous and starts two tasks — an immediate icon refresh and
a long-lived D-Bus listener:

```python
def init_service() -> None:
    create_task(update_ethernet_icon())
    create_task(setup_listeners())
```

- **D-Bus listener** — `setup_listeners()` (`setup.py:35`) resolves the ethernet device via
  `get_ethernet_device()` and, if present, awaits its `properties_changed` stream, kicking an icon
  refresh on every change (event-driven, no polling). If there is no ethernet device it returns
  immediately.
- **Icon publisher** — `update_ethernet_icon()` (`setup.py:18`) is debounced (leading + trailing,
  0.6 s window) so bursts of D-Bus property changes collapse into a single icon update. It reads
  `get_ethernet_device_state()` and maps each `NetState` to a glyph, then dispatches
  `StatusIconsRegisterAction`.

There is no `Subscriptions` return value / explicit teardown — `init_service()` returns `None` and
the two tasks live for the process lifetime.

## System / Hardware Integration

- **NetworkManager over D-Bus** (`sdbus_async.networkmanager`) via `get_system_bus()`. The manager
  enumerates devices and picks the first whose `device_type == DeviceType.ETHERNET`
  (`ethernet_manager.py:33`).
- **State mapping** — `get_ethernet_device_state()` (`ethernet_manager.py:43`) translates
  NetworkManager `DeviceState` values into the coarse `NetState` used for the icon; all D-Bus calls
  are wrapped in a 10 s `wait_for` timeout.
- Read-only: no `send_command` / privileged operations.

## Cross-Service Interactions

- **Shares `NetState`** with `030-wifi` (see State above).
- Dispatches into the core **status-icons** slice (`StatusIconsRegisterAction`); no other service
  reads ethernet output directly.

## Configuration

No env vars or secrets. Constants live in `constants.py`: `ETHERNET_STATE_ICON_ID = 'ethernet:state'`
and `ETHERNET_STATE_ICON_PRIORITY = -13`.

## Testing & Development Notes

Related tests:

| Test                                        | Tier        | What it covers                                                     |
| ------------------------------------------- | ----------- | ---------------------------------------------------------------- |
| `tests/integration/test_services.py`        | Integration | Asserts the `ethernet` service registers and the store snapshot matches. |
| `tests/store/test_wifi_hotspot_reducer.py`  | Unit        | Not an ethernet test, but imports the shared `NetState` enum — a rename/reorder of `NetState` will surface here. |

> There is **no dedicated unit test** for this service. It is pure I/O glue (D-Bus → icon) with no
> reducer, so a `tests/store` unit test would have little to bite on; the `NetState` → glyph mapping
> in `update_ethernet_icon()` is the one piece worth a small pure test if you extract it from the
> debounced coroutine.

**Maintenance when you change this service:**

- **`NetState` enum shape** → this is shared with `030-wifi`; changing members affects both services'
  icons and any snapshot that renders them → regenerate store/window snapshots (never hand-edit) and
  check the wifi reducer tests still import cleanly.
- **Icon id/priority or glyphs** → regenerate window snapshots so the status-bar fixture matches;
  do not hand-edit snapshot files.
- The D-Bus path requires a real NetworkManager (Linux/on-device); on a dev host `get_system_bus()`
  is unavailable, so live link-state transitions are verified on-device.

To exercise manually: on-device, plug/unplug the ethernet cable and confirm the status-bar icon
tracks connected → pending → disconnected.
