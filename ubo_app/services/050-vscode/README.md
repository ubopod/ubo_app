# VSCode Service (`050-vscode`)

## Overview

The VSCode service manages a [VS Code Remote Tunnel](https://code.visualstudio.com/docs/remote/tunnels)
on the device: it downloads the platform-appropriate `code` CLI, logs in through the GitHub device
flow (scanned QR), installs/restarts the tunnel service, and reports live tunnel status (running,
service installed, tunnel name) in Settings → Remote. Everything runs in user space via the
downloaded `code` binary — no system-manager/root involvement.

It loads in the `050-` tier (system/remote-access services), after networking is up, since the tunnel
needs connectivity to reach the VS Code relay.

## Files

| Path            | Purpose                                                                             |
| --------------- | ---------------------------------------------------------------------------------- |
| `ubo_handle.py` | Service registration (`service_id='vscode'`); returns `init_service()`'s subscriptions. |
| `setup.py`      | Runtime: dynamic menu, GitHub login flow, download, 1 s status poll, event wiring. |
| `reducer.py`    | Reducer for the `vscode` slice; on login transition emits login + restart events.  |
| `commands.py`   | `code` CLI wrappers: status probe, service install/uninstall/restart, rename, locking. |
| `constants_.py` | Platform CLI-name detection, download URL, and on-disk paths (note trailing `_`).  |

State/action/event types live in
[`ubo_app/store/services/vscode.py`](../../store/services/vscode.py).

> The constants module is `constants_.py` (trailing underscore), imported as `from constants_ import
> …`, to avoid shadowing another `constants` on the service `sys.path`.

## State

Slice: `state.vscode` — [`VSCodeState`](../../store/services/vscode.py):

| Field                | Type                    | Meaning                                                   |
| -------------------- | ----------------------- | -------------------------------------------------------- |
| `is_pending`         | `bool` (default `True`) | A service op (install/restart/rename) is in flight.      |
| `is_downloading`     | `bool`                  | The `code` binary is being (re)downloaded.               |
| `is_binary_installed`| `bool`                  | The `code` CLI exists on disk.                           |
| `is_logged_in`       | `bool \| None`          | GitHub tunnel auth; `None` = unknown/checking.           |
| `status`             | `VSCodeStatus \| None`  | Tunnel status: `is_service_installed`, `is_running`, `name`. |

## Actions & Events

Per the store contract, **events are emitted only from the reducer**.

| Action                        | Reducer result                                                               |
| ----------------------------- | --------------------------------------------------------------------------- |
| `VSCodeStartDownloadingAction`| `is_downloading = True`.                                                     |
| `VSCodeDoneDownloadingAction` | `is_downloading = False`.                                                    |
| `VSCodeSetPendingAction`      | `is_pending = True`.                                                         |
| `VSCodeSetStatusAction`       | Stores binary/login/tunnel status (clears `is_pending`); on a `False → True` login transition also emits `NotificationsAddAction` (success flash) **and** both `VSCodeLoginEvent` + `VSCodeRestartEvent`. |

`VSCodeRestartEvent` is handled in-service by `commands.restart` (subscribed in `init_service`).
`VSCodeLoginEvent` has no in-core subscriber — it is forwarded to gRPC clients (registered in
`ubo_app/rpc/_class_registry.py`).

## Runtime & Setup

`init_service()` (`setup.py:408`) is **async** (`ubo_handle.py` awaits it) and returns a
`Subscriptions` list:

```python
register_action('vscode:open_menu', _open_vscode_menu)
store.dispatch(
    RegisterSettingAppAction(
        label='VSCode', icon='󰨞',
        action_id='vscode:open_menu', category=SettingsCategory.REMOTE,
    ),
)
register_path_menu_matcher(
    'vscode:settings',
    create_settings_path_matcher('vscode:', VSCODE_MENU_ID),
)
await check_status()
end_event = asyncio.Event()
create_task(_monitor_status(end_event))
return [store.subscribe_event(VSCodeRestartEvent, restart), end_event.set]
```

Reactive pieces:

- `update_vscode_dynamic_menu` (`setup.py:344`) — `@store.autorun(lambda state: state.vscode)`;
  rebuilds `vscode:main` (Download/Redownload, Login/Logout, Show URL when running) and dynamically
  registers a `vscode:show-url:{name}` handler for the current tunnel name (tracked in
  `_vscode_show_url_action_ids`, unregistered/re-registered as the name changes).
- **GitHub login** — `start_login()` opens a status render; `_perform_login()` runs `code tunnel …
  user login --provider github`, scrapes the device-code URL/code into a QR render, then (on exit)
  installs the service and pops both views.
- **Download** — `download_code()` `curl`s `CODE_BINARY_URL` and unpacks it, holding `download_lock`
  for the whole rewrite so the status poll can't exec a half-written binary (`ETXTBSY`).
- **Status poll** — `_monitor_status()` calls `commands.check_status()` every second; the debounced
  probe runs `code tunnel user show` (safe gate) then `code tunnel status`, and only raises a sticky
  error after `_FAILURE_NOTIFICATION_THRESHOLD` consecutive failures (clearing it on recovery). The
  returned `end_event.set` stops the loop on teardown.

## User Interface

- **Settings entry:** `SettingsCategory.REMOTE`, label **VSCode** (icon `󰨞`).
- **Dynamic menu:** `VSCODE_MENU_ID = 'vscode:main'` via `UpdateDynamicMenuAction` (dumb UI).
- **Action handlers:** `vscode:download`, `vscode:login`, `vscode:logout`, `vscode:open_menu`, and
  the dynamic `vscode:show-url:{name}`.
- **Path matcher:** `create_settings_path_matcher('vscode:', VSCODE_MENU_ID)`.
- **Renders:** login QR (device URL + code) and the tunnel URL
  (`CODE_TUNNEL_URL_PREFIX = 'https://vscode.dev/tunnel/'` + name).

## System / Hardware Integration

No system manager / root. All operations shell out to the downloaded user-space `code` binary
(`CODE_BINARY_PATH`): `tunnel user login|logout|show`, `tunnel status`, `tunnel service
install|uninstall`, `tunnel restart`, `tunnel rename`. The binary is fetched with `curl` and unpacked
with `tar`. `download_lock` serializes downloads against status probes to avoid `ETXTBSY`.

## Cross-Service Interactions

None at the store level. Dependencies are `010-notifications` (login success, download/status/service
errors) and the core menu/render/settings infrastructure.

## Configuration

- **`constants_.py`:** `get_cli_tool_name()` maps `platform.system()`/`machine()` to the VS Code CLI
  build; `CODE_BINARY_URL` = `https://code.visualstudio.com/sha/download?build=stable&os=<build>`;
  `CODE_BINARY_PATH = DATA_PATH / 'code'`; `CODE_DOWNLOAD_PATH = CACHE_PATH / 'code.tar.gz'`.
- **`setup.py`:** `VSCODE_MENU_ID`, `CODE_TUNNEL_URL_PREFIX`.
- **`commands.py`:** `download_lock`, `_FAILURE_NOTIFICATION_THRESHOLD = 3`.

No env vars or secrets (GitHub auth is handled entirely by the `code` device flow).

## Testing & Development Notes

Related tests:

| Test                                 | Tier        | What it covers                                                      |
| ------------------------------------ | ----------- | ------------------------------------------------------------------ |
| `tests/integration/test_services.py` | Integration | Asserts the `vscode` service registers and the store snapshot matches. |

> There is currently **no dedicated unit test** for the VSCode reducer. It has a non-trivial branch
> worth covering (the `is_logged_in False → True` transition emitting a notification +
> `VSCodeLoginEvent` + `VSCodeRestartEvent`). Add `tests/store/test_vscode_reducer.py` modeled on
> `tests/store/test_tailscale_reducer.py` (which shows the `sys.path` import + cleanup for a
> non-package service reducer).

**Maintenance when you change this service:**

- **State shape** (`VSCodeState`/`VSCodeStatus`) or dynamic-menu output → regenerate store/window
  snapshots (never hand-edit); this updates the `test_services.py` fixture.
- **Reducer branches** (esp. the login-transition emit) → cover with a `tests/store` unit test,
  preferred over a flaky E2E.
- **Status parsing** in `commands.py` (JSON from `code tunnel status`) and the platform mapping in
  `constants_.py` → guard with small pure-logic tests (`get_cli_tool_name()` is a good candidate).
- Runtime depends on downloading and exec'ing the `code` binary and reaching the VS Code relay —
  verify download/login/tunnel on-device. Preserve the invariants: hold `download_lock` around
  (re)downloads and gate `code tunnel status` behind a successful `user show` (it otherwise busy-loops
  when no tunnel is running).

To exercise manually: Settings → Remote → VSCode, Download the CLI, scan the GitHub login QR, then
open the tunnel URL and confirm the sub-heading tracks the tunnel name/running state.

See [`docs/architecture/UI_REDUX_ARCHITECTURE.md`](../../../docs/architecture/UI_REDUX_ARCHITECTURE.md)
for the service → action → reducer → state → event flow and the dumb-client architecture.
