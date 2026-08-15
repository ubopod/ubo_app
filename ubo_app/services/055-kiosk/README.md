# Browser Kiosk Service

Drives a full-screen **browser kiosk** (and an optional terminal) across the
Raspberry Pi's two HDMI outputs. Each output can independently show a browser,
a login terminal, or nothing. This is separate from the device's primary
headless LVGL/Kivy display — it gives the HDMI ports a usable desktop-class
surface (by default the local Web UI) without a full desktop environment.

The kiosk is built on **Weston** (a Wayland compositor) running as a system
`systemd` unit, mirroring how the LightDM integration works. Packages are
installed on demand; the unit is started/enabled from the on-device menu.

## Where it fits

This is a standard `ubo_app` service (priority `055`) following the usual Redux
contract:

| Concern              | File                                                     |
| -------------------- | -------------------------------------------------------- |
| Service registration | `ubo_handle.py`                                          |
| State / actions      | `ubo_app/store/services/kiosk.py`                        |
| Reducer              | `reducer.py`                                             |
| Side effects & UI    | `setup.py`                                               |
| Weston config (pure) | `kiosk_config.py`                                        |
| systemd unit         | `ubo_app/system/services/ubo-kiosk.service.tmpl`         |

The service holds **no privilege of its own**. Anything that touches the system
(installing packages, starting/enabling the unit) is delegated to the
privileged **system manager** over its socket via `send_command(...)` — the
same boundary every other system-touching service uses.

## State model

`KioskState` (`ubo_app/store/services/kiosk.py`) is intentionally small:

- `is_installed` / `is_installing` — whether the kiosk packages are present.
- `is_active` — whether the `ubo-kiosk` unit is currently running.
- `is_enabled` — whether it's enabled to start on boot (`None` = "checking…",
  rendered as a transient placeholder so the UI never shows a stale toggle).
- `connected_ports` — which HDMI outputs are physically plugged in (from sysfs).
- `port_roles` — the core configuration: a `KioskPortRole`
  (`BROWSER` / `TERMINAL` / `OFF`) per HDMI output (`hdmi_a_1`, `hdmi_a_2`).

`port_roles` is the only user-owned configuration and is **persisted** (one
`register_persistent_store` entry per port), so role assignments survive
restarts and reinstalls.

## UI: dumb, store-driven menus

The service follows the repo's "dumb UI" convention — it never builds menus
imperatively in response to clicks. Instead, `store.autorun` selectors watch
kiosk state and **re-emit** the menu whenever state changes:

- `update_kiosk_hdmi_menu` → the top-level **Browser Kiosk** menu (install /
  start-stop / enable-disable / per-port role entries). The exact items shown
  are derived purely from `KioskState`.
- `update_kiosk_port_menus` → a Browser/Terminal/Off **selection menu** per
  port, built with the shared `build_selection_menu` helper.

Menu clicks dispatch through registered **action handlers**
(`register_action`, e.g. `kiosk:install`, `kiosk:start`, `kiosk:set_role:…`).
Per-port role handlers are generated in a loop over `PORTS × KioskPortRole`.

### Navigation: nested under Display

The kiosk menus live under **Settings → Display → HDMI**, but the kiosk service
owns only the `hdmi` subtree. The Display service (`000-display`) renders the
`display:` root and the `timeout` leaf; it pushes a plain `hdmi` nav key and
deliberately does **not** read kiosk state. The kiosk service registers its own
`register_path_menu_matcher` that claims paths ending in `…/display:/hdmi`
(and `…/display:/hdmi/<port>`), keeping the two services decoupled.

## Config generation & apply flow

`kiosk_config.py` is **pure** (no I/O except the final `write_kiosk_config`) and
turns `port_roles` into two artifacts under `~/.config/ubo-kiosk/`:

1. **`weston.ini`** — one `[output]` block per HDMI port. Surfaces are pinned to
   a specific output via kiosk-shell's `app-ids=`, using deterministic Wayland
   app-ids (`ubo-kiosk-browser`, `ubo-kiosk-terminal`). An `OFF` port gets
   `mode=off`.
2. **`kiosk-clients.sh`** — a launcher script referenced by Weston's
   `[autolaunch]`.

A single Weston compositor owns the DRM master and drives **both** outputs.
Because `[autolaunch]` only accepts one path, a generated wrapper script
launches whichever clients are needed (`foot` for terminals, Chromium for
browsers pointed at the local Web UI). Weston restarts the autolaunch target if
it exits (`watch=true`), so the script keeps a foreground process alive — a
Chromium restart loop when a browser is present, otherwise `foot`, otherwise an
idle wait.

Config is (re)written and applied reactively:

```
KioskSetPortRoleAction
        │  (reducer)
        ▼
state.port_roles updated  ──emits──▶  KioskApplyConfigEvent
                                            │  (subscriber in setup.py)
                                            ▼
                              write_kiosk_config(port_roles)
                              + restart ubo-kiosk if it's running
```

Emitting the event from the **reducer** (not the action handler) keeps the
reducer pure and follows the repo rule that events originate only from reducers.

## System integration

| Operation        | How                                                                          |
| ---------------- | ---------------------------------------------------------------------------- |
| Install packages | `send_command('package', 'install', 'kiosk')` → system manager `_install_kiosk` |
| Start/stop/etc.  | `send_command('service', 'ubo-kiosk', <cmd>)` (start/stop/restart/enable/disable) |
| State refresh    | `check_kiosk` (package + `is-enabled`), `detect_connected_ports` (sysfs)      |
| Live status      | `monitor_unit('ubo-kiosk.service', …)` keeps `is_active` in sync             |

`_install_kiosk` (in `system_manager/package.py`) installs `weston`, `foot`,
and Chromium. The `ubo-kiosk` unit runs as `root` (`User=root`, matching
`ubo-system`/`ubo-hotspot`) rather than the unprivileged `ubo` user: the
Raspberry Pi OS `weston` package isn't built with `libseat` support (confirmed
via `ldd` — no `libseat.so` dependency) and ships no `weston-launch` setuid
helper, so its DRM backend has no way to get device access without either a
real `logind` session or root. Getting `ubo` a genuine `logind` session for a
plain systemd service would need `PAMName=login` + a bound TTY, which is
fragile for a headless kiosk unit — running as root is what the DRM backend's
"direct launcher" path expects and is the simplest working option here.

Even as root, the direct launcher still needs an open VT to do its mode-switch
ioctls — without one it fails with `<stdin> not a vt`. The unit binds
`TTYPath=/dev/tty2` (a VT unused by the console `getty`) with
`StandardInput=tty`, which weston picks up via its inherited stdin fd; no
`--tty=` CLI flag is needed (and none is accepted — that flag only exists for
the `logind` launcher path, so passing it under `User=root` fails with `fatal:
unhandled option`). `StandardOutput=journal` / `StandardError=journal` are set
explicitly because binding `StandardInput=tty` otherwise makes systemd default
weston's own output to that same TTY instead of the journal, hiding real
crashes from `journalctl`.

Because everything under weston (including Chromium) inherits `root`,
Chromium's own sandbox refuses to start (`Running as root without
--no-sandbox is not supported`) — `kiosk_config.py`'s Chromium launch command
passes `--no-sandbox`; the loss is moot since the parent process is already
unsandboxed root.

The `ubo-kiosk` unit declares `Conflicts=lightdm.service` so the kiosk and a
full LightDM desktop can't fight over the display.

`kiosk` is added to the system manager's `PACKAGE_WHITELIST` and `ubo-kiosk` to
its service whitelist; the unit is registered in `bootstrap.py` (system scope,
disabled by default).

## Low-level decisions & caveats

- **Single compositor, app-id pinning.** One Weston instance with
  `kiosk-shell` pins each client to an output by app-id. This avoids running two
  compositors competing for one DRM device.
- **Chromium naming is image-dependent.** The package name (`chromium-browser`
  vs `chromium`) and the Wayland app-id mechanism (`--class`) vary across Pi OS
  releases. Install tries both package names; `CHROMIUM_APP_ID` / `CHROMIUM_BIN`
  in `kiosk_config.py` are marked for confirmation against the validated device
  recipe.
- **`IS_RPI` guard.** Config is only written to disk on real hardware;
  off-device the service still runs (state, menus, tests) but skips the Weston
  file writes.
- **`is_enabled is None`.** Enable/disable dispatches first clear the flag to
  `None` (rendered as a placeholder) and re-check after a short delay, so the
  toggle reflects the real `systemctl is-enabled` result rather than an
  optimistic guess.

## Tests

Pure, Kivy-free unit tests:

- `tests/store/test_kiosk_reducer.py` — reducer transitions and the
  `KioskApplyConfigEvent` emission.
- `tests/store/test_kiosk_config.py` — `weston.ini` / launcher-script generation
  for the various role combinations.
