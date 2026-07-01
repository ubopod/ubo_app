# Tailscale Service (`050-tailscale`)

## Overview

The Tailscale service manages the [Tailscale](https://tailscale.com) mesh-VPN client on the device:
installing/uninstalling the `tailscale` package, signing in (via a scanned login URL),
connecting/disconnecting the tunnel, signing out, and reflecting the daemon's `BackendState` as a
status line in Settings → Remote.

It loads in the `050-` tier (system/remote-access services), after networking is up, since a VPN
overlay is only meaningful once the base network stack exists.

## Files

| Path            | Purpose                                                                          |
| --------------- | -------------------------------------------------------------------------------- |
| `ubo_handle.py` | Service registration (`service_id='tailscale'`); wires reducer + `init_service()`. |
| `setup.py`      | Runtime: dynamic menu, QR sign-in flow, action handlers, Settings entry, matcher. |
| `reducer.py`    | Pure reducer for the `tailscale` slice.                                          |
| `commands.py`   | `send_command`/subprocess wrappers: install, status (`--json`), up/down, logout. |

State/action types live in
[`ubo_app/store/services/tailscale.py`](../../store/services/tailscale.py).

## State

Slice: `state.tailscale` — [`TailscaleState`](../../store/services/tailscale.py):

| Field           | Type           | Meaning                                                            |
| --------------- | -------------- | ----------------------------------------------------------------- |
| `is_downloading`| `bool`         | An install is in flight (menu suppresses actions).                |
| `is_installed`  | `bool \| None` | Package installed; `None` = unknown/pending.                      |
| `is_active`     | `bool`         | Derived: `backend_state == 'Running'`.                            |
| `backend_state` | `str \| None`  | Raw `tailscale status --json` `BackendState` (`Running`/`Stopped`/`NeedsLogin`/…). |

## Actions & Events

The reducer is a pure state-mapper — it emits no events and dispatches no cross-service actions.

| Action                          | Effect                                                                |
| ------------------------------- | -------------------------------------------------------------------- |
| `TailscaleStartDownloadingAction`| `is_downloading = True`.                                            |
| `TailscaleDoneDownloadingAction` | `is_downloading = False`.                                           |
| `TailscaleSetPendingAction`      | Clears `is_installed`/`backend_state` to `None`, `is_active = False` (uninstall). |
| `TailscaleSetStatusAction`       | Stores `is_installed`/`backend_state` and derives `is_active`.       |

Side effects live in `commands.py`/`setup.py`, not the reducer.

## Runtime & Setup

`init_service()` (`setup.py:263`) registers the Settings entry, an open-menu action that re-checks
status, and a path matcher, then kicks an initial `check_status()`:

```python
register_action('tailscale:open_menu', _open_tailscale_menu)
store.dispatch(
    RegisterSettingAppAction(
        label='Tailscale',
        icon='󰖂',
        action_id='tailscale:open_menu',
        category=SettingsCategory.REMOTE,
    ),
)
register_path_menu_matcher(
    'tailscale:settings',
    create_settings_path_matcher('tailscale:', TAILSCALE_MENU_ID),
)
create_task(check_status())
```

Reactive pieces:

- `update_tailscale_dynamic_menu` (`setup.py:170`) — `@store.autorun(lambda state:
  state.tailscale)`; rebuilds `tailscale:main` per `backend_state` (Sign in when `NeedsLogin`;
  Connect/Sign out when `Stopped`; Show URL/Disconnect/Sign out when `Running`; Install/Uninstall).
  Action handlers registered once via a module-level `_tailscale_actions_registered` flag.
- **QR sign-in** — `start_signin()` opens a status render; `_perform_signin()` runs `tailscale up`,
  scrapes the `https://login.tailscale.com/…` URL, swaps to a QR render via `UpdateRenderPropsAction`,
  and pops when the CLI exits.
- **Status polling** — `commands.check_status()` (debounced, leading-edge) runs `tailscale status
  --json`, reads `BackendState`, and dispatches `TailscaleSetStatusAction`.

## User Interface

- **Settings entry:** `SettingsCategory.REMOTE`, label **Tailscale** (icon `󰖂`).
- **Dynamic menu:** `TAILSCALE_MENU_ID = 'tailscale:main'` via `UpdateDynamicMenuAction` (dumb UI).
- **Action handlers:** `tailscale:install`, `:uninstall`, `:sign-in`, `:sign-out`, `:connect`,
  `:disconnect`, `:show-url`, `:open_menu` via `register_action`.
- **Path matcher:** `create_settings_path_matcher('tailscale:', TAILSCALE_MENU_ID)`.
- **Renders:** sign-in QR and the admin console URL (`ADMIN_CONSOLE_URL =
  'https://login.tailscale.com/admin/machines'`).

## System / Hardware Integration

- **Install/uninstall** are privileged → delegated to the system manager via a dedicated `tailscale`
  command (not the generic `package` one used by lightdm/rpi-connect):
  `send_command('tailscale', 'install'|'uninstall', has_output=True)`.
- **Tunnel control** shells out to the `tailscale` CLI directly: `up` (connect / sign-in), `down`
  (disconnect), `logout` (sign out), and `status --json` for observability.

## Cross-Service Interactions

None at the store level. Dependencies are the **system manager** (privileged install),
`010-notifications` (install/status/connect failures), and the core menu/render/settings
infrastructure.

## Configuration

No env vars or secrets. Constants: `TAILSCALE_MENU_ID = 'tailscale:main'` and `ADMIN_CONSOLE_URL`.

## Testing & Development Notes

Related tests:

| Test                                  | Tier        | What it covers                                                     |
| ------------------------------------- | ----------- | ----------------------------------------------------------------- |
| `tests/store/test_tailscale_reducer.py` | Unit      | Install/download flags and the `backend_state == 'Running'` → `is_active` derivation. Shows the `sys.path` import + cleanup pattern for a non-package service reducer. |
| `tests/integration/test_services.py`  | Integration | Asserts the `tailscale` service registers and the store snapshot matches. |

**Maintenance when you change this service:**

- **State shape** (`TailscaleState`) or dynamic-menu output → regenerate store/window snapshots
  (never hand-edit); this updates the `test_services.py` fixture.
- **Reducer branches** → extend `tests/store/test_tailscale_reducer.py` (prefer a small pure-reducer
  test over an E2E).
- **Status parsing** in `commands.py` (JSON `BackendState`) → guard changes with a parser test.
- Runtime depends on the `tailscale` CLI/daemon and the system manager for install — verify
  install/sign-in/connect on-device.

To exercise manually: Settings → Remote → Tailscale, install, scan the sign-in QR, then
Connect/Disconnect and confirm the sub-heading tracks `backend_state`.

See [`docs/architecture/UI_REDUX_ARCHITECTURE.md`](../../../docs/architecture/UI_REDUX_ARCHITECTURE.md)
for the service → action → reducer → state → event flow and the dumb-client architecture.
