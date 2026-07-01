# SSH Service (`050-ssh`)

## Overview

The SSH service lets the user start/stop and enable/disable the device's OpenSSH server
(`ssh.service`) from the on-device menu, and surfaces its live status as a colored icon in the
Settings → Remote category. It is a thin control/observability layer over `systemd`: the service
itself owns no SSH logic, it only reflects and toggles the unit's state.

It loads in the `050-` tier (system/remote-access services) — after core hardware, display, and
networking are up, since remote access is only meaningful once the network stack exists.

## Files

| Path                                  | Purpose                                                                 |
| ------------------------------------- | ----------------------------------------------------------------------- |
| `ubo_handle.py`                       | Service registration; wires the reducer and calls `init_service()`.     |
| `setup.py`                            | Runtime: dynamic menu, status autoruns, unit monitoring, action handlers. |
| `reducer.py`                          | Pure reducer for the `ssh` state slice (`is_active`, `is_enabled`).     |

State/action types live outside the service in
[`ubo_app/store/services/ssh.py`](../../store/services/ssh.py).

## State

Slice: `state.ssh` — [`SSHState`](../../store/services/ssh.py):

| Field        | Type            | Meaning                                                              |
| ------------ | --------------- | ------------------------------------------------------------------- |
| `is_active`  | `bool`          | Whether `ssh.service` is currently running.                         |
| `is_enabled` | `bool \| None`  | Whether the unit is enabled at boot. `None` = unknown/in-flight (shown as `...`). |

## Actions & Events

The reducer is a pure state-mapper — it emits no events and dispatches no cross-service actions.
(Per the store contract, events are only ever emitted from reducers; this reducer has none.)

| Action                        | Effect                                                                |
| ----------------------------- | --------------------------------------------------------------------- |
| `SSHUpdateStateAction`        | Patches `is_active` and/or `is_enabled` (fields left `None` are untouched). |
| `SSHClearEnabledStateAction`  | Resets `is_enabled` to `None` — used to show `...` while a toggle is applied. |

Side effects (calling `systemctl`) live in `setup.py`, not the reducer.

## Runtime & Setup

`init_service()` (`setup.py:162`) registers the Settings entry and a path matcher, then kicks off
an initial status check and a long-lived unit monitor:

```python
store.dispatch(
    RegisterSettingAppAction(
        priority=1,
        category=SettingsCategory.REMOTE,
        label='SSH',
        icon='󰣀',
        action_id='ssh:open_menu',
    ),
)
create_task(check_is_ssh_enabled())
create_task(
    monitor_unit(
        'ssh.service',
        lambda status: store.dispatch(
            SSHUpdateStateAction(is_active=status in ('active', 'activating', 'reloading')),
        ),
    ),
)
```

Reactive pieces:

- `update_ssh_dynamic_menu` (`setup.py:75`) — `@store.autorun(lambda state: state.ssh)`; rebuilds
  the `ssh:main` dynamic menu whenever the slice changes (Start/Stop toggle + Enable/Disable item,
  or a `...` placeholder while `is_enabled is None`). It also lazily registers the menu's action
  handlers on first run.
- `ssh_icon` / `ssh_title` (`setup.py:135`, `:148`) — autoruns that render the colored status glyph
  (`RUNNING_COLOR`/`STOPPED_COLOR`) used in the menu title.

The state-changing helpers (`start_ssh_service`, `enable_ssh_service`, …) dispatch
`SSHClearEnabledStateAction` first (so the UI shows `...`), issue the privileged command, wait, then
re-poll `check_is_ssh_enabled()`.

## User Interface

- **Settings entry:** registered under `SettingsCategory.REMOTE` via `RegisterSettingAppAction`.
- **Dynamic menu:** `SSH_MENU_ID = 'ssh:main'`, populated through `UpdateDynamicMenuAction` (the
  "dumb UI" pattern — the client renders whatever items the service pushes).
- **Action handlers:** `ssh:start`, `ssh:stop`, `ssh:enable`, `ssh:disable`, `ssh:open_menu`
  registered via `register_action`.
- **Path matcher:** `create_settings_path_matcher('ssh:', SSH_MENU_ID)` so deep-links into SSH
  settings resolve to the dynamic menu.

## System / Hardware Integration

SSH server control is a **privileged** operation, so the service never calls `systemctl` directly.
Instead it delegates to the privileged system manager over the local socket:

```python
await send_command('service', 'ssh', 'start')   # also: stop / enable / disable
```

Status is observed (not polled tightly) via `monitor_unit('ssh.service', ...)` and
`is_unit_enabled('ssh')` from `ubo_app.utils.monitor_unit`.

## Cross-Service Interactions

None at the store level — the service neither dispatches to nor reads other services' slices. Its
only external dependency is the **system manager** (for `systemctl`) and the core menu/settings
infrastructure (`RegisterSettingAppAction`, `UpdateDynamicMenuAction`, the action and view
registries).

## Configuration

No env vars or secrets. The only constant is the module-level `SSH_MENU_ID = 'ssh:main'`.

## Testing & Development Notes

Related tests:

| Test                                  | Tier        | What it covers                                                       |
| ------------------------------------- | ----------- | ------------------------------------------------------------------- |
| `tests/integration/test_services.py`  | Integration | Asserts the `ssh` service registers and the store snapshot matches. |

> There is currently **no dedicated unit test** for the SSH reducer — it is exercised only via the
> all-services registration test. The reducer is pure and trivial to cover (feed
> `SSHUpdateStateAction`/`SSHClearEnabledStateAction`, assert the resulting `SSHState`); adding
> `tests/store/test_ssh_reducer.py` is a good first contribution if you touch this service.

**Maintenance when you change this service:**

- **State shape** (`SSHState`) or the dynamic-menu output → regenerate store/window snapshots
  (never hand-edit them); this updates the `test_services.py` fixture.
- Runtime behavior depends on `send_command`/`monitor_unit`, which require the system manager and a
  real `systemd` — on a dev host these are mocked or no-ops, so verify the start/enable path
  on-device.

To exercise manually: Settings → Remote → SSH, toggle Start/Enable, and confirm the icon color and
`is_active`/`is_enabled` transitions.
