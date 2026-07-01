# Desktop / LightDM Service (`050-lightdm`)

## Overview

The LightDM service lets the user install the Raspberry Pi desktop and then start/stop and
enable/disable the display manager (`lightdm.service`) from the on-device menu, surfacing its live
status as a colored icon in Settings → System. It owns no desktop logic itself — it is a thin
control/observability layer over `apt` (for install) and `systemd` (for the unit).

It loads in the `050-` tier (system/remote-access services), after core hardware, display, and
networking are up, since a desktop/display-manager toggle is only meaningful once those exist. The
LightDM desktop is also a prerequisite for RPi Connect screen sharing (`050-rpi-connect`).

## Files

| Path            | Purpose                                                                        |
| --------------- | ------------------------------------------------------------------------------ |
| `ubo_handle.py` | Service registration (`service_id='lightdm'`); wires the reducer + `init_service()`. |
| `setup.py`      | Runtime: dynamic menu, status/title autoruns, unit monitoring, install/toggle handlers. |
| `reducer.py`    | Pure reducer for the `lightdm` slice.                                          |

State/action types live outside the service in
[`ubo_app/store/services/lightdm.py`](../../store/services/lightdm.py).

## State

Slice: `state.lightdm` — [`LightDMState`](../../store/services/lightdm.py):

| Field          | Type   | Meaning                                                                |
| -------------- | ------ | --------------------------------------------------------------------- |
| `is_active`    | `bool` | Whether `lightdm.service` is currently running.                       |
| `is_enabled`   | `bool` | Whether the unit is enabled at boot. Transiently set to `None` by `LightDMClearEnabledStateAction` while a toggle is applied (shown as `...`). |
| `is_installed` | `bool` | Whether the desktop package (`raspberrypi-ui-mods`) is installed.     |
| `is_installing`| `bool` | Whether an `apt` install is in flight (menu shows an "Installing…" placeholder). |

## Actions & Events

The reducer is a pure state-mapper — it emits no events and dispatches no cross-service actions.
(Per the store contract, events are only ever emitted from reducers; this reducer has none.)

| Action                          | Effect                                                              |
| ------------------------------- | ------------------------------------------------------------------ |
| `LightDMUpdateStateAction`      | Patches `is_active`/`is_enabled`/`is_installed`/`is_installing` (fields left `None` are untouched). |
| `LightDMClearEnabledStateAction`| Resets `is_enabled` to `None` — used to show `...` while enable/disable is applied. |

Side effects (`apt`/`systemctl`) live in `setup.py`, not the reducer.

## Runtime & Setup

`init_service()` (`setup.py:237`) registers the Settings entry and a path matcher, then kicks off an
initial status check and a long-lived unit monitor:

```python
register_action('lightdm:open_menu', _open_lightdm_menu)
store.dispatch(
    RegisterSettingAppAction(
        priority=0,
        category=SettingsCategory.SYSTEM,
        label='Desktop',
        icon='󰍹',
        action_id='lightdm:open_menu',
    ),
)
create_task(check_lightdm())
create_task(monitor_unit('lightdm.service', lambda status: store.dispatch(...)))
```

Reactive pieces:

- `update_lightdm_dynamic_menu` (`setup.py:135`) — `@store.autorun(lambda state: state.lightdm)`;
  rebuilds the `lightdm:main` dynamic menu whenever the slice changes (Install item when
  uninstalled, otherwise Start/Stop + Enable/Disable, with a `...` placeholder while `is_enabled is
  None`). It lazily registers the menu's action handlers on first run.
- `lightdm_icon` / `lightdm_title` (`setup.py:93`, `:106`) — autoruns rendering the colored status
  glyph (`RUNNING_COLOR`/`STOPPED_COLOR`) used in the menu title.
- `check_lightdm()` (`setup.py:222`) gathers `is_unit_enabled('lightdm')` and
  `is_package_installed('raspberrypi-ui-mods')` and dispatches a combined `LightDMUpdateStateAction`.

The state-changing helpers dispatch `LightDMClearEnabledStateAction` first (so the UI shows `...`),
issue the privileged command, wait, then re-poll `check_lightdm()`.

## User Interface

- **Settings entry:** `SettingsCategory.SYSTEM`, labeled **Desktop** (icon `󰍹`) — note the menu label
  differs from the service `label='LightDM'`.
- **Dynamic menu:** `LIGHTDM_MENU_ID = 'lightdm:main'`, populated via `UpdateDynamicMenuAction` (the
  "dumb UI" pattern — the client renders whatever items the service pushes).
- **Action handlers:** `lightdm:install`, `lightdm:start`, `lightdm:stop`, `lightdm:enable`,
  `lightdm:disable`, `lightdm:open_menu` via `register_action`.
- **Path matcher:** `create_settings_path_matcher('lightdm:', LIGHTDM_MENU_ID)`.

## System / Hardware Integration

Both install and service control are **privileged**, so the service never calls `apt`/`systemctl`
directly — it delegates to the privileged system manager over the local socket:

```python
await send_command('package', 'install', 'lightdm', has_output=True)  # install
await send_command('service', 'lightdm', 'start')  # also: stop / enable / disable
```

Status is observed (not tightly polled) via `monitor_unit('lightdm.service', ...)` and
`is_unit_enabled('lightdm')` from `ubo_app.utils.monitor_unit`; installed-state is probed with
`is_package_installed` from `ubo_app.utils.apt`.

## Cross-Service Interactions

None at the store level — the service neither dispatches to nor reads other services' slices. Its
only dependencies are the **system manager** (for `apt`/`systemctl`), `010-notifications` (an install
failure notification), and the core menu/settings infrastructure. Note the reverse dependency:
`050-rpi-connect` reads `state.lightdm.is_active` to warn when screen sharing is unavailable.

## Configuration

No env vars or secrets. The only constant is `LIGHTDM_MENU_ID = 'lightdm:main'`.

## Testing & Development Notes

Related tests:

| Test                                 | Tier        | What it covers                                                      |
| ------------------------------------ | ----------- | ------------------------------------------------------------------ |
| `tests/integration/test_services.py` | Integration | Asserts the `lightdm` service registers and the store snapshot matches. |

> There is currently **no dedicated unit test** for the LightDM reducer — it is exercised only via
> the all-services registration test. The reducer is pure and trivial to cover (feed
> `LightDMUpdateStateAction`/`LightDMClearEnabledStateAction`, assert the resulting `LightDMState`);
> adding `tests/store/test_lightdm_reducer.py` (mirroring `tests/store/test_tailscale_reducer.py`) is
> a good first contribution if you touch this service.

**Maintenance when you change this service:**

- **State shape** (`LightDMState`) or the dynamic-menu output → regenerate store/window snapshots
  (never hand-edit them); this updates the `test_services.py` fixture.
- **Reducer branches** → add/extend a small pure-reducer unit test in `tests/store` rather than a
  flaky E2E.
- Runtime depends on `send_command`/`monitor_unit`/`is_package_installed`, which need a real system
  manager and `systemd`/`apt` — on a dev host these are mocked or no-ops, so verify the
  install/start/enable path on-device.

To exercise manually: Settings → System → Desktop, install the desktop, then toggle Start/Enable and
confirm the icon color and `is_active`/`is_enabled` transitions.

See [`docs/architecture/UI_REDUX_ARCHITECTURE.md`](../../../docs/architecture/UI_REDUX_ARCHITECTURE.md)
for the service → action → reducer → state → event flow and the dumb-client architecture.
