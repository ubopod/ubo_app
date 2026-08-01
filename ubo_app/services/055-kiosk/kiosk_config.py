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
FOOT_APP_ID = 'ubo-kiosk-terminal'
CHROMIUM_APP_ID_PREFIX = 'ubo-kiosk-browser'
CHROMIUM_BIN = 'chromium-browser'

KIOSK_CONFIG_DIR = Path(f'/home/{USERNAME}/.config/ubo-kiosk')
WESTON_INI_PATH = KIOSK_CONFIG_DIR / 'weston.ini'
CLIENTS_SCRIPT_PATH = KIOSK_CONFIG_DIR / 'kiosk-clients.sh'

# (state field name, weston/DRM output name)
_OUTPUTS: tuple[tuple[str, str], ...] = (
    ('hdmi_a_1', 'HDMI-A-1'),
    ('hdmi_a_2', 'HDMI-A-2'),
)


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
            lines.append(f'app-ids={FOOT_APP_ID}')
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
    script keeps a foreground process alive: it backgrounds the terminal and one
    self-restarting Chromium loop per browser output, then ``wait``s on them
    (or idles when there are no clients at all).
    """
    selections = (
        (field_name, getattr(port_selections, field_name))
        for field_name, _output_name in _OUTPUTS
    )
    browser_ports = [
        (field_name, selection)
        for field_name, selection in selections
        if selection.role == KioskPortRole.BROWSER
    ]
    has_terminal = any(
        getattr(port_selections, field_name).role == KioskPortRole.TERMINAL
        for field_name, _output_name in _OUTPUTS
    )

    foot_cmd = f'foot --app-id={FOOT_APP_ID} -- login -f {USERNAME}'

    lines: list[str] = ['#!/bin/bash', 'set -u', '']

    if has_terminal:
        lines += [f'{foot_cmd} &', '']

    for field_name, selection in browser_ports:
        url = _resolve_url(selection.dashboard_id, dashboards)
        # --no-sandbox: weston (and everything it launches) runs as root, since
        # this weston build has no libseat support; Chromium refuses to start as
        # root with its sandbox enabled.
        chromium_cmd = (
            f'{CHROMIUM_BIN} --ozone-platform=wayland --no-sandbox '
            f'--user-data-dir={_browser_profile_dir(field_name)} '
            f'--class={_browser_app_id(field_name)} --kiosk "{url}"'
        )
        lines += [
            '(',
            '    while true; do',
            f'        {chromium_cmd}',
            '        sleep 2',
            '    done',
            ') &',
            '',
        ]

    if has_terminal or browser_ports:
        lines.append('wait')
    else:
        lines.append('sleep infinity')

    lines.append('')
    return '\n'.join(lines)


def write_kiosk_config(
    port_selections: KioskPortSelections,
    dashboards: tuple[KioskDashboard, ...],
) -> None:
    """Write ``weston.ini`` and the executable launcher script to disk."""
    KIOSK_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    WESTON_INI_PATH.write_text(generate_weston_ini(port_selections, dashboards))
    CLIENTS_SCRIPT_PATH.write_text(generate_clients_script(port_selections, dashboards))
    CLIENTS_SCRIPT_PATH.chmod(0o755)
