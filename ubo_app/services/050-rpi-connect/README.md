# RPi Connect Service (`050-rpi-connect`)

## Overview

The RPi Connect service manages [Raspberry Pi Connect](https://connect.raspberrypi.com) on the
device: installing/uninstalling the `rpi-connect` package, signing in (via a scanned QR login URL),
signing out, starting/stopping the per-user `rpi-connect` service, and reporting live status
(screen-sharing / remote-shell session counts) in Settings → Remote.

It loads in the `050-` tier (system/remote-access services), after network and display are up, since
remote access only makes sense once connectivity exists. Screen sharing additionally depends on the
LightDM desktop (`050-lightdm`), which this service reads to warn the user when it is missing.

## Files

| Path            | Purpose                                                                          |
| --------------- | -------------------------------------------------------------------------------- |
| `ubo_handle.py` | Service registration (`service_id='rpi_connect'`); wires reducer + `init_service()`. |
| `setup.py`      | Runtime: dynamic menu, QR sign-in flow, action handlers, Settings entry, matcher. |
| `reducer.py`    | Reducer for the `rpi_connect` slice; emits a login notification + event.         |
| `commands.py`   | Subprocess/`send_command` wrappers: install, status, service start/stop, sign-out. |

State/action/event types live in
[`ubo_app/store/services/rpi_connect.py`](../../store/services/rpi_connect.py).

## State

Slice: `state.rpi_connect` — [`RPiConnectState`](../../store/services/rpi_connect.py):

| Field           | Type                        | Meaning                                                 |
| --------------- | --------------------------- | ------------------------------------------------------- |
| `is_downloading`| `bool`                      | An install is in flight (menu suppresses actions).      |
| `is_active`     | `bool`                      | Whether the user `rpi-connect` service is running.      |
| `is_installed`  | `bool \| None`              | Package installed; `None` = unknown/pending.            |
| `is_signed_in`  | `bool \| None`              | Signed in to a RPi Connect account; `None` = unknown.   |
| `status`        | `RPiConnectStatus \| None`  | Session counts: `screen_sharing_sessions`, `remote_shell_sessions` (each `int \| None`). |

## Actions & Events

Per the store contract, **events are emitted only from the reducer**.

| Action                              | Reducer result                                                       |
| ----------------------------------- | ------------------------------------------------------------------- |
| `RPiConnectStartDownloadingAction`  | `is_downloading = True`.                                            |
| `RPiConnectDoneDownloadingAction`   | `is_downloading = False`.                                           |
| `RPiConnectSetPendingAction`        | Clears `is_installed`/`is_signed_in`/`status` to `None` (uninstall). |
| `RPiConnectUpdateServiceStateAction`| Patches `is_active`.                                                |
| `RPiConnectSetStatusAction`         | Stores install/sign-in/status; on a `False → True` sign-in transition also emits `NotificationsAddAction` (success flash) **and** `RPiConnectLoginEvent`. |

`RPiConnectLoginEvent` has no in-core subscriber — it is emitted from the reducer and forwarded to
gRPC clients (registered in `ubo_app/rpc/_class_registry.py`), which may react to it.

## Runtime & Setup

`init_service()` (`setup.py:270`) registers the Settings entry, an open-menu action that re-checks
status, and a path matcher, then kicks an initial `check_is_active()`:

```python
register_action('rpi-connect:open_menu', _open_rpi_connect_menu)
store.dispatch(
    RegisterSettingAppAction(
        label='RPi Connect',
        icon='󰌕',
        action_id='rpi-connect:open_menu',
        category=SettingsCategory.REMOTE,
    ),
)
register_path_menu_matcher(
    'rpi-connect:settings',
    create_settings_path_matcher('rpi_connect:', RPI_CONNECT_MENU_ID),
)
create_task(check_is_active())
```

Reactive pieces:

- `update_rpi_connect_dynamic_menu` (`setup.py:179`) — `@store.autorun(lambda state:
  state.rpi_connect)`; rebuilds the `rpi-connect:main` menu (Install/Uninstall, Sign in/out,
  Start/Stop, Show URL when sessions are active). Action handlers are registered once, guarded by a
  module-level `_rpi_connect_actions_registered` flag (never a global).
- **QR sign-in** — `start_signin()` opens a status render then `_perform_signin()` runs
  `rpi-connect signin`, scrapes the `Complete sign in by visiting <url>` line and swaps the render to
  a QR code via `UpdateRenderPropsAction`, popping the view when the CLI exits.
- **Status polling** — `commands.check_status()` (debounced, leading-edge) runs `rpi-connect status`,
  parses signed-in state and session counts, and dispatches `RPiConnectSetStatusAction`.

## User Interface

- **Settings entry:** `SettingsCategory.REMOTE`, label **RPi Connect** (icon `󰌕`).
- **Dynamic menu:** `RPI_CONNECT_MENU_ID = 'rpi-connect:main'` via `UpdateDynamicMenuAction` (dumb UI).
- **Action handlers:** `rpi-connect:install`, `:uninstall`, `:sign-in`, `:sign-out`, `:start`,
  `:stop`, `:show-url`, `:open_menu` via `register_action`.
- **Path matcher:** `create_settings_path_matcher('rpi_connect:', RPI_CONNECT_MENU_ID)`.
- **Renders:** sign-in QR (`kind='qr_code'`) and the devices admin URL
  (`https://connect.raspberrypi.com/devices`).

## System / Hardware Integration

- **Install/uninstall** are privileged → delegated to the system manager:
  `send_command('package', 'install'|'uninstall', 'rpi-connect', has_output=True)`.
- **Service start/stop** target the *per-user* unit and are run directly (no root needed):
  `systemctl --user start|stop rpi-connect`; liveness via
  `is_unit_active('rpi-connect', is_user_service=True)`.
- **Sign in/out/status** shell out to the `rpi-connect` CLI directly (`commands.py`,
  `setup._perform_signin`).

## Cross-Service Interactions

- **Reads `state.lightdm.is_active`** (via `@store.with_state`) in `start_service()` to warn — with a
  sticky notification — that screen sharing will be unavailable without LightDM running.
- Dispatches into `010-notifications` (login success, install/status failures) and core
  menu/render/settings actions.
- The system manager provides privileged `apt` operations.

## Configuration

No env vars or secrets. Constants: `RPI_CONNECT_MENU_ID = 'rpi-connect:main'`; the admin/devices URL
is inlined in `setup.py`.

## Testing & Development Notes

Related tests:

| Test                                 | Tier        | What it covers                                                      |
| ------------------------------------ | ----------- | ------------------------------------------------------------------ |
| `tests/integration/test_services.py` | Integration | Asserts the `rpi_connect` service registers and the store snapshot matches. |

> There is currently **no dedicated unit test** for the RPi Connect reducer. It has a non-trivial
> branch worth covering (the `is_signed_in False → True` transition that emits a notification +
> `RPiConnectLoginEvent`). Add `tests/store/test_rpi_connect_reducer.py` modeled on
> `tests/store/test_tailscale_reducer.py` (which shows the `sys.path` dance for importing a reducer
> from a non-package `NNN-name` service directory).

**Maintenance when you change this service:**

- **State shape** (`RPiConnectState`/`RPiConnectStatus`) or dynamic-menu output → regenerate
  store/window snapshots (never hand-edit); this updates the `test_services.py` fixture.
- **Reducer branches** (esp. the login-transition emit) → cover with a `tests/store` unit test,
  preferred over a flaky E2E.
- **Status parsing** in `commands.py` (regex over `rpi-connect status`) → guard changes with a small
  parser test.
- Runtime depends on the `rpi-connect` CLI, the per-user `rpi-connect` systemd unit, and the system
  manager for `apt` — verify install/sign-in/start on-device.

To exercise manually: Settings → Remote → RPi Connect, install, scan the sign-in QR, start the
service (watch for the LightDM warning if the desktop is off), and confirm session counts.

See [`docs/architecture/UI_REDUX_ARCHITECTURE.md`](../../../docs/architecture/UI_REDUX_ARCHITECTURE.md)
for the service → action → reducer → state → event flow and the dumb-client architecture.
