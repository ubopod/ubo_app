# IP Service (`030-ip`)

## Overview

The IP service tracks two things: the device's **local network interfaces / addresses** (via
`psutil`) and its **internet reachability** (via a long-running `ping 8.8.8.8`). It exposes the
interfaces as a browsable dynamic menu under Settings → Network, publishes an internet status-bar
icon, and stores an `is_connected` flag that other services depend on.

It loads in the `030-` (network) tier alongside `030-wifi` and `030-ethernet`, after display/core so
it can render its menu and reflect connectivity from boot.

See [`docs/architecture/UI_REDUX_ARCHITECTURE.md`](../../../docs/architecture/UI_REDUX_ARCHITECTURE.md)
for the store/action/event model.

## Files

| Path            | Purpose                                                                          |
| --------------- | ------------------------------------------------------------------------------- |
| `ubo_handle.py` | Registration (`service_id='ip'`); async `setup` registers the reducer, returns `init_service()`'s subscriptions. |
| `setup.py`      | Runtime: interface poller, ping-based connectivity monitor, dynamic menu autorun, path matcher. |
| `reducer.py`    | Pure reducer for the `ip` slice; emits the internet status icon on connectivity change. |
| `constants.py`  | Icon id/priority (`ip:internet-state`, `-11`) and `IP_ADDRESSES_MENU_ID`.        |

Store types: [`ubo_app/store/services/ip.py`](../../store/services/ip.py).

## State

Slice: `state.ip` — [`IpState`](../../store/services/ip.py):

| Field          | Type                              | Meaning                                                        |
| -------------- | --------------------------------- | ------------------------------------------------------------- |
| `interfaces`   | `Sequence[IpNetworkInterface]`    | Per-interface IPv4 addresses discovered via `psutil`.         |
| `is_connected` | `bool \| None`                    | Ping-based internet reachability; `None` until first probe.   |

`IpNetworkInterface` (`store/services/ip.py:27`) carries `name` and `ip_addresses: Sequence[str]`.
Unlike ethernet/wifi, this slice does **not** use the shared `NetState` enum — reachability is a
plain bool derived from ping replies.

## Actions & Events

The reducer is a pure state-mapper. It emits no domain events; the one side effect it produces is a
core `StatusIconsRegisterAction` returned from the reducer (per the store contract, effect actions
originate in the reducer, side effects run in `setup.py`).

| Action                     | Reducer result                                                              |
| -------------------------- | -------------------------------------------------------------------------- |
| `IpUpdateInterfacesAction` | Replaces `interfaces`.                                                      |
| `IpSetIsConnectedAction`   | Updates `is_connected` **and** returns `StatusIconsRegisterAction` (globe glyph when connected, red slashed-globe when not). |

On `InitAction` the reducer seeds `IpState(interfaces=[])`.

## Runtime & Setup

`init_service()` (`setup.py:238`) is **async** (awaited from `ubo_handle.py`), registers the Settings
entry + path matcher, starts two monitors, and returns a `Subscriptions` list for teardown:

```python
end_event = asyncio.Event()
create_task(monitor_connections(end_event))
create_task(monitor_interfaces(end_event))
return [end_event.set]
```

- **Interface poller** — `monitor_interfaces()` (`setup.py:161`) calls `load_network_interfaces()`
  every second. That helper reads `psutil.net_if_addrs()`, keeps only `AF_INET` addresses, and
  **skips the dispatch when the interface set is unchanged** (module-level `_last_interfaces` guard)
  to avoid churning the store.
- **Connectivity monitor** — `monitor_connections()` (`setup.py:172`) spawns a persistent
  `ping 8.8.8.8 -s 0` subprocess, collects reply lines with timestamps, and every 0.25 s recomputes
  `is_connected` from replies newer than `PING_TIMEOUT` (3 s), dispatching `IpSetIsConnectedAction`.
  The ping subprocess self-restarts on exit/error.
- **Dynamic menu autorun** — `update_ip_dynamic_menu` (`setup.py:80`,
  `@store.autorun(lambda state: state.ip.interfaces)`) pushes the interfaces list menu
  (`IP_ADDRESSES_MENU_ID`) and one detail menu per interface, re-registering per-interface action
  handlers (`ip:open-interface:<name>`) on each rebuild (the "dumb UI" pattern).

Teardown: the returned `end_event.set` stops both monitor loops (and terminates the ping subprocess).

## User Interface

- **Settings entry:** `RegisterSettingAppAction` under `SettingsCategory.NETWORK`, label
  "IP Addresses", priority 0.
- **Dynamic menus (dumb UI):** `IP_ADDRESSES_MENU_ID = 'ip:addresses'` lists interfaces; each
  interface gets its own dynamic menu (`menu_id == interface.name`) listing its addresses, pushed via
  `UpdateDynamicMenuAction`. Interface rows dispatch `StackPushMenuAction(menu_key=<name>)`.
- **Status icon:** the internet-state glyph (`ip:internet-state`, priority `-11`) is registered from
  the reducer on every `IpSetIsConnectedAction`.
- **Path matcher:** `_ip_path_matcher` (`setup.py:251`) resolves `ip:settings` deep-links —
  `…/ip:` → the addresses menu, `…/ip:/<iface>` → that interface's detail menu.

## System / Hardware Integration

- **`psutil`** for interface/address enumeration (no root needed).
- **`ping` subprocess** (`/usr/bin/env ping 8.8.8.8`) for reachability — this is the source of truth
  for `is_connected`, not NetworkManager. See the memory note that heavy per-second dispatch should
  stay off the store's critical path; here the poller debounces via the unchanged-interfaces guard.

## Cross-Service Interactions

`state.ip` is one of the more widely consumed slices:

- **`030-wifi`** reads `state.ip.is_connected` (guarded with `hasattr`) to auto-stop a *transient*
  onboarding hotspot once a real route appears (`030-wifi/setup.py:251`,
  `pages/create_wireless_connection.py:519`, `pages/main.py:407`).
- **`090-web-ui`** reads `state.ip.is_connected` (`090-web-ui/setup.py:210`).
- **`080-docker`** reads `state.ip.interfaces` for its app menus (`080-docker/menus.py:437`) and its
  image reducer references `IpUpdateInterfacesAction`.

All external readers guard with `hasattr(state, 'ip')`, since focused tests may load without this
slice.

## Configuration

No env vars or secrets. Constants: `INTERNET_STATE_ICON_ID`/`INTERNET_STATE_ICON_PRIORITY` and
`IP_ADDRESSES_MENU_ID` in `constants.py`; `PING_TIMEOUT = 3.0` in `setup.py`.

## Testing & Development Notes

Related tests:

| Test                                  | Tier        | What it covers                                                       |
| ------------------------------------- | ----------- | ------------------------------------------------------------------- |
| `tests/integration/test_services.py`  | Integration | Asserts the `ip` service registers and the store snapshot matches.  |

> There is currently **no dedicated unit test** for the IP reducer or the dynamic-menu builder.
> Both are pure and easy to cover — feed `IpUpdateInterfacesAction` / `IpSetIsConnectedAction` and
> assert the resulting `IpState` plus the emitted `StatusIconsRegisterAction`, and assert the
> `MenuItemData` shape from `update_ip_dynamic_menu`. Adding `tests/store/test_ip_reducer.py` is a
> good first contribution if you touch this service.

**Maintenance when you change this service:**

- **State shape** (`IpState`, `IpNetworkInterface`) or **dynamic-menu output** → regenerate
  store/window snapshots (never hand-edit); this updates the `test_services.py` fixture. Remember
  downstream consumers (`030-wifi`, `090-web-ui`, `080-docker`) read this slice.
- **Reducer branches** (icon selection, new actions) → prefer a small `tests/store` pure-reducer unit
  test over the integration tier.
- The ping monitor and `psutil` behavior depend on a real network/OS; on a dev host `is_connected`
  and interface lists are environment-dependent, so verify connectivity transitions on-device.

To exercise manually: Settings → Network → IP Addresses to browse interfaces; pull the network and
confirm the internet icon flips to the red slashed-globe within a few seconds.
