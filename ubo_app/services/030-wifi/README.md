# Wi-Fi Service (`030-wifi`)

## Overview

The Wi-Fi service manages the device's wireless connectivity: scanning for networks, creating and
connecting to connections (via keypad, on-screen QR, or the web dashboard), reporting connection
state, and owning the **Wi-Fi hotspot** (AP mode on `wlan0`) used for onboarding and
internet-sharing. It talks to NetworkManager over D-Bus for the read/observe side and delegates
privileged hotspot control to the system manager.

It loads in the `030-` (network) tier alongside `030-ethernet` and `030-ip`, after display and core
services so it can render menus/notifications and reflect connectivity.

> **Ownership note:** the hotspot belongs to *this* service, not `090-web-ui`. Consumers that need
> hotspot info read the `wifi` slice (consumer → owner); the shared QR builder lives in
> `ubo_app/utils/hotspot_qr.py`.

## Files

| Path                                  | Purpose                                                                    |
| ------------------------------------- | ------------------------------------------------------------------------- |
| `ubo_handle.py`                       | Registration; returns `init_service()`'s subscription list.               |
| `setup.py`                            | Runtime: scan/update loop, D-Bus listeners, hotspot lifecycle, matchers.  |
| `reducer.py`                          | Pure reducer for the `wifi` slice; maps actions → state/events.           |
| `constants.py`                        | Menu IDs, status-icon id/priority, `get_signal_icon()` helper.            |
| `wifi_manager.py`                     | NetworkManager (D-Bus) client: scan, list, connect, device state.         |
| `pages/main.py`                       | Connection menu + status icon autoruns; connect/disconnect/forget handlers. |
| `pages/create_wireless_connection.py` | The "add a network" flow (scan-pick, input-driven creation).              |
| `pages/wifi_input_descriptions.py`    | QR + WebUI input-form descriptions for SSID/password entry.               |

Store types: [`ubo_app/store/services/wifi.py`](../../store/services/wifi.py).

## State

Slice: `state.wifi` — [`WiFiState`](../../store/services/wifi.py):

| Field                  | Type                              | Meaning                                            |
| ---------------------- | --------------------------------- | -------------------------------------------------- |
| `connections`          | `Sequence[WiFiConnection] \| None`| Known/scanned networks; `None` while (re)scanning. |
| `state`                | `NetState`                        | Device-level connectivity (shared enum with ethernet). |
| `current_connection`   | `WiFiConnection \| None`          | The `CONNECTED` connection, if any.                |
| `has_visited_onboarding`| `bool \| None`                   | Persisted; gates the one-time onboarding prompt.   |
| `is_hotspot_running`   | `bool`                            | Whether the AP-mode hotspot is currently up.       |
| `hotspot_user_enabled` | `bool`                            | Hotspot was *deliberately* toggled on (survives auto-stop). |

`WiFiConnection` carries `ssid`, `state`, `signal_strength`, `type` (`WiFiType`), `hidden`, and
optional `password`.

## Actions & Events

Per the store contract, **events are emitted only from the reducer**; `setup.py` subscribes to them
and performs the async/privileged side effects. This request→event→side-effect split keeps the
reducer pure.

| Action (in)                       | Reducer result                                                      |
| --------------------------------- | ------------------------------------------------------------------- |
| `WiFiUpdateRequestAction`         | → `WiFiUpdateRequestEvent` (triggers a scan); `reset=True` clears list first. |
| `WiFiUpdateAction`                | Stores fresh `connections`/`state`/`current_connection`.            |
| `WiFiInputConnectionAction`       | → `WiFiInputConnectionEvent` (open the add-network input flow).     |
| `WiFiStartHotspotAction(mode)`    | → `WiFiStartHotspotEvent(mode)`.                                    |
| `WiFiStopHotspotAction`           | → `WiFiStopHotspotEvent`.                                           |
| `WiFiSetHotspotRunningAction`     | Syncs `is_hotspot_running` / `hotspot_user_enabled` post-side-effect.|
| `WiFiSetHasVisitedOnboardingAction`| Persists onboarding flag; → `WiFiUpdateRequestEvent`.             |

On `InitAction` the reducer seeds an empty state **and** dispatches `WiFiUpdateRequestAction`, so a
first scan runs at boot.

## Runtime & Setup

`init_service()` (`setup.py:243`) does the heavy lifting and returns a `Subscriptions` list for
clean teardown:

- **Scan/refresh:** `update_wifi_list()` (debounced, leading-edge) pulls connections via
  `wifi_manager.get_connections()` and dispatches `WiFiUpdateAction`. It's kicked at startup and on
  every `WiFiUpdateRequestEvent`.
- **D-Bus listener:** `setup_listeners()` awaits the wireless device's `properties_changed` stream
  and re-scans on any change — live, event-driven updates rather than polling.
- **Onboarding:** `_check_connection()` waits, checks `has_gateway()` / saved SSIDs, and (on a Ubo
  Pod) shows a sticky "No internet connection" notification or (elsewhere) dispatches
  `WiFiInputConnectionAction`.
- **Hotspot lifecycle:** `start_hotspot`/`stop_hotspot` subscribe to the start/stop events and call
  `send_command('hotspot', 'start'|'stop', ...)`, then sync state via `WiFiSetHotspotRunningAction`.
  A `_stop_hotspot_when_connected` autorun tears down a *transient* onboarding hotspot once a real
  route appears — but leaves a `hotspot_user_enabled` internet-sharing hotspot up:

  ```python
  @store.autorun(lambda state: (
      state.ip.is_connected if hasattr(state, 'ip') else None,
      state.wifi.is_hotspot_running,
      state.wifi.hotspot_user_enabled,
  ))
  def _stop_hotspot_when_connected(data):
      is_connected, is_hotspot_running, user_enabled = data
      if is_connected and is_hotspot_running and not user_enabled:
          store.dispatch(WiFiStopHotspotAction())
  ```

- **Persistence:** `register_persistent_store('wifi_has_visited_onboarding', ...)`.
- **Subscriptions returned:** `WiFiUpdateRequestEvent → request_scan`, `WiFiInputConnectionEvent →
  input flow`, hotspot start/stop, and `NotificationsClearEvent` (to drop the hotspot QR page).

## User Interface

- **Settings entry:** `RegisterSettingAppAction` under `SettingsCategory.NETWORK`.
- **Dynamic menus (dumb UI):** `pages/main.py` autoruns push `UpdateDynamicMenuAction` for the
  connections list (`wifi:connections`) and hotspot toggle; `create_wireless_connection.py` pushes
  the ad-hoc scan-results menu (`wifi:hotspot-scan`). Per-SSID action handlers
  (`wifi:connect:<ssid>`, `:disconnect:`, `:forget:`) are (re)registered as the menu rebuilds.
- **Status icon:** an autorun on `state.wifi` publishes the signal-strength glyph
  (`WIFI_STATE_ICON_ID`, `get_signal_icon`) into the status bar, reflecting both client and hotspot
  modes.
- **Input forms:** `pages/wifi_input_descriptions.py` defines `QRCodeInputDescription` (scan a Wi-Fi
  QR) and `WebUIInputDescription` variants (full SSID+password / password-only) used by the
  add-network flow across keypad and web-dashboard input methods.
- **Path matchers:** registered for `wifi:settings`, `wifi:connections`, and the imperative
  `wifi:hotspot-scan` frame so deep-links resolve correctly.

## System / Hardware Integration

- **NetworkManager over D-Bus** (`sdbus_async.networkmanager`) for all read/observe/connect
  operations in `wifi_manager.py`; uses `tenacity` retries around flaky D-Bus calls.
- **Privileged hotspot control** via `send_command('hotspot', ...)` to the system manager (bringing
  `wlan0` up in AP mode is root-only; see also the reference note that hotspot start must
  `systemctl restart hostapd`, handled system-side).

## Cross-Service Interactions

- Reads `state.ip.is_connected` (guarded with `hasattr`) to decide transient-hotspot auto-stop.
- Shares `NetState` with `030-ethernet`.
- Dispatches into `010-notifications` (onboarding / hotspot notifications) and core menu/render
  actions (`OpenRenderAction`, `StackPushMenuAction`, `RegisterSettingAppAction`).
- Uses shared utilities: `ubo_app/utils/hotspot_qr.py`, `ubo_app/utils/network.py`,
  `ubo_app/utils/persistent_store.py`.

## Configuration

- `WEB_UI_HOTSPOT_PASSWORD` (from `ubo_app.constants`) — the hotspot password shown in the connect
  notification/QR.
- `IS_UBO_POD` / `IS_UBO_POD`-gated onboarding behavior.
- Menu IDs and the signal-icon table live in `constants.py`.

## Testing & Development Notes

Related tests (run `uv run poe test:unit` for the unit tier; flows/integration run in Docker or
on-device):

| Test                                        | Tier        | What it covers                                                        |
| ------------------------------------------- | ----------- | -------------------------------------------------------------------- |
| `tests/flows/test_wifi.py`                  | Flow (E2E)  | The full add-network **setup flow** via real gRPC keypad presses with window + store snapshots. **RPi-only** (`@skipif(not IS_RPI)`); a module fixture runs `tests/flows/wifi_setup.sh` once to reset NetworkManager to a clean slate. |
| `tests/integration/test_services.py`        | Integration | Asserts the `wifi` service registers and the store snapshot matches. |
| `tests/store/test_wifi_hotspot_reducer.py`  | Unit        | Reducer behavior for the hotspot start/stop/running actions.         |
| `tests/store/test_wifi_scan.py`             | Unit        | Scan/update action → state transitions.                             |
| `tests/store/test_wifi_input_descriptions.py`| Unit       | Shape of the QR/WebUI input descriptions (`pages/wifi_input_descriptions.py`). |
| `tests/store/test_wifi_qr.py`               | Unit        | Wi-Fi QR parsing/formatting (`utils/hotspot_qr.py`).                |

**Maintenance when you change this service:**

- **State shape or menu items** (`WiFiState`, dynamic-menu output) → regenerate store/window
  snapshots (`docker … --override-store-snapshots --override-window-snapshots`), which updates
  `test_services.py` and `test_wifi.py` fixtures. Never hand-edit snapshot files.
- **Input forms** (`pages/wifi_input_descriptions.py`) → update `test_wifi_input_descriptions.py`.
- **Reducer actions/events** → cover the new branch in `test_wifi_scan.py` /
  `test_wifi_hotspot_reducer.py`; prefer a small pure-reducer unit test over extending the RPi-only
  flow.
- **Environment quirks:** the D-Bus/NetworkManager and `send_command` layers require a real Linux
  networking stack, so live behavior is verified on-device. The `ip` slice may be absent in focused
  tests, which is why the hotspot autorun guards `hasattr(state, 'ip')`.

To exercise manually: Settings → Network → WiFi to scan/connect; toggle the hotspot and confirm the
connect notification/QR appears and that gaining a route auto-stops a transient hotspot but not a
user-enabled one.
