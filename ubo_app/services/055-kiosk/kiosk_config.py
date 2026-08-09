"""Pure generation of the Weston kiosk configuration and client launcher.

The kiosk runs a single Weston compositor (one DRM master) driving both HDMI
outputs. Surfaces are pinned to outputs via kiosk-shell ``app-ids=``. Weston's
``[autolaunch]`` accepts a single path, so a generated wrapper script launches
the terminal (foot) and one Chromium per browser output as needed.
"""

from __future__ import annotations

from pathlib import Path

from ubo_app.constants import USERNAME, WEB_UI_LISTEN_PORT
from ubo_app.store.services.kiosk import (
    KioskDashboard,
    KioskPortRole,
    KioskPortSelection,
    KioskPortSelections,
)

# Deterministic Wayland app-ids so kiosk-shell ``app-ids=`` pinning is reliable.
# foot honours ``--app-id``; Chromium's Wayland app-id is set from ``--class``.
# NOTE: confirm Chromium's app-id honours ``--class`` on the validated device
# recipe; adjust ``CHROMIUM_APP_ID_PREFIX`` / ``CHROMIUM_BIN`` if it differs.
FOOT_APP_ID_PREFIX = 'ubo-kiosk-terminal'
CHROMIUM_APP_ID_PREFIX = 'ubo-kiosk-browser'
CHROMIUM_BIN = 'chromium-browser'

# --no-sandbox: weston (and everything it launches) runs as root — this weston
# build has no libseat support — and Chromium refuses to start as root with its
# sandbox enabled. The remaining flags suppress the crash-restore / first-run /
# translate UI that would otherwise arm after this launcher's unclean restarts
# and silently hold keyboard focus, starving the page of key events.
CHROMIUM_KIOSK_FLAGS = (
    '--ozone-platform=wayland --no-sandbox --no-first-run '
    '--no-default-browser-check --disable-session-crashed-bubble '
    '--hide-crash-restore-bubble --disable-features=Translate'
)

# Clear the "did not exit cleanly" markers in a profile before each launch so
# the crash-restore bubble never arms (belt-and-braces with the flags above).
# Operates on the ``$prefs`` shell variable set in the launch loop.
_PREFS_RESET_SED = (
    'sed -i '
    "'s/\"exited_cleanly\":false/\"exited_cleanly\":true/;"
    "s/\"exit_type\":\"[^\"]*\"/\"exit_type\":\"Normal\"/' "
    '"$prefs"'
)

KIOSK_CONFIG_DIR = Path(f'/home/{USERNAME}/.config/ubo-kiosk')
WESTON_INI_PATH = KIOSK_CONFIG_DIR / 'weston.ini'
CLIENTS_SCRIPT_PATH = KIOSK_CONFIG_DIR / 'kiosk-clients.sh'

# (state field name, weston/DRM output name)
_OUTPUTS: tuple[tuple[str, str], ...] = (
    ('hdmi_a_1', 'HDMI-A-1'),
    ('hdmi_a_2', 'HDMI-A-2'),
)


def _terminal_app_id(field_name: str) -> str:
    return f'{FOOT_APP_ID_PREFIX}-{field_name}'


def _browser_app_id(field_name: str) -> str:
    return f'{CHROMIUM_APP_ID_PREFIX}-{field_name}'


def _browser_profile_dir(field_name: str) -> str:
    # Each Chromium output needs its own profile: two instances sharing the
    # default profile collide on Chromium's per-profile singleton lock — the
    # second hands its URL off to the first and exits, and the restart loop
    # turns that into an endless relaunch/reload cycle.
    return str(KIOSK_CONFIG_DIR / f'chromium-{field_name}')


def _resolve_url(
    dashboard_id: str | None,
    dashboards: tuple[KioskDashboard, ...],
) -> str:
    """Resolve a selection's dashboard id to its URL, defaulting to the Web UI."""
    for dashboard in dashboards:
        if dashboard.id == dashboard_id:
            return dashboard.url
    return f'http://localhost:{WEB_UI_LISTEN_PORT}'


def generate_weston_ini(
    port_selections: KioskPortSelections,
    dashboards: tuple[KioskDashboard, ...],
) -> str:
    """Generate the ``weston.ini`` contents for the given per-port selections."""
    del dashboards  # URLs live in the launcher script; app-ids only pin surfaces.
    lines: list[str] = [
        '[core]',
        'shell=kiosk-shell.so',
        'xwayland=false',
        'require-input=false',
        '',
    ]

    for field_name, output_name in _OUTPUTS:
        selection: KioskPortSelection = getattr(port_selections, field_name)
        lines += ['[output]', f'name={output_name}']
        if selection.role == KioskPortRole.OFF:
            lines.append('mode=off')
        elif selection.role == KioskPortRole.BROWSER:
            lines.append(f'app-ids={_browser_app_id(field_name)}')
        elif selection.role == KioskPortRole.TERMINAL:
            lines.append(f'app-ids={_terminal_app_id(field_name)}')
        lines.append('')

    lines += [
        '[autolaunch]',
        f'path={CLIENTS_SCRIPT_PATH}',
        'watch=true',
        '',
    ]
    return '\n'.join(lines)


def generate_clients_script(
    port_selections: KioskPortSelections,
    dashboards: tuple[KioskDashboard, ...],
) -> str:
    """Generate the launcher script that starts foot and/or Chromium.

    Weston restarts the autolaunch target if it exits (``watch=true``), so the
    script keeps a foreground process alive: it backgrounds one foot terminal
    per terminal output and one self-restarting Chromium loop per browser
    output, then ``wait``s on them (or idles when there are no clients at all).
    """
    terminal_ports = [
        field_name
        for field_name, _output_name in _OUTPUTS
        if getattr(port_selections, field_name).role == KioskPortRole.TERMINAL
    ]
    browser_ports = [
        (field_name, getattr(port_selections, field_name))
        for field_name, _output_name in _OUTPUTS
        if getattr(port_selections, field_name).role == KioskPortRole.BROWSER
    ]

    lines: list[str] = ['#!/bin/bash', 'set -u', '']

    # One foot per terminal output, each pinned to its output by a distinct
    # app-id — a single shared instance would only ever show on one screen.
    for field_name in terminal_ports:
        foot_cmd = (
            f'foot --app-id={_terminal_app_id(field_name)} -- login -f {USERNAME}'
        )
        lines += [f'{foot_cmd} &', '']

    for field_name, selection in browser_ports:
        url = _resolve_url(selection.dashboard_id, dashboards)
        profile_dir = _browser_profile_dir(field_name)
        chromium_cmd = (
            f'{CHROMIUM_BIN} {CHROMIUM_KIOSK_FLAGS} '
            f'--user-data-dir={profile_dir} '
            f'--class={_browser_app_id(field_name)} --kiosk "{url}"'
        )
        lines += [
            '(',
            '    while true; do',
            f'        prefs="{profile_dir}/Default/Preferences"',
            f'        [ -f "$prefs" ] && {_PREFS_RESET_SED}',
            f'        {chromium_cmd}',
            '        sleep 2',
            '    done',
            ') &',
            '',
        ]

    if terminal_ports or browser_ports:
        lines.append('wait')
    else:
        lines.append('sleep infinity')

    lines.append('')
    return '\n'.join(lines)


def _write_if_different(path: Path, content: str) -> bool:
    """Write *content* to *path* unless it is already there; report if written."""
    try:
        if path.read_text() == content:
            return False
    except (FileNotFoundError, OSError):
        pass
    path.write_text(content)
    return True


def write_kiosk_config(
    port_selections: KioskPortSelections,
    dashboards: tuple[KioskDashboard, ...],
) -> bool:
    """Write ``weston.ini`` and the launcher script; report whether they changed.

    The return value is what lets a caller avoid restarting the kiosk — and with
    it reloading whatever is on screen — when the files it just wrote are the
    ones that were already there.
    """
    KIOSK_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # Deliberately not short-circuited: both files must be written.
    weston_changed = _write_if_different(
        WESTON_INI_PATH,
        generate_weston_ini(port_selections, dashboards),
    )
    clients_changed = _write_if_different(
        CLIENTS_SCRIPT_PATH,
        generate_clients_script(port_selections, dashboards),
    )
    CLIENTS_SCRIPT_PATH.chmod(0o755)
    return weston_changed or clients_changed
