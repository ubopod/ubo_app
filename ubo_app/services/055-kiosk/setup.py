"""Browser Kiosk service module.

Manages a Weston + Chromium kiosk (and an optional foot terminal) across the
two HDMI outputs. Each output shows a *selection*: the terminal, a specific
named browser dashboard, or nothing. Dashboards (name + URL) are user-managed;
``Ubo WebUI`` is a permanent built-in. Packages are installed on demand; the
systemd unit ``ubo-kiosk`` is started/enabled from the GUI, mirroring LightDM.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from kiosk_config import write_kiosk_config

from ubo_app.colors import DANGER_COLOR
from ubo_app.store.core.bindable_actions import register_bindable_action
from ubo_app.store.core.types import (
    ExecuteMenuActionAction,
    MenuItemData,
    StackPopAction,
    UpdateDynamicMenuAction,
)
from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    WebUIInputDescription,
)
from ubo_app.store.main import store
from ubo_app.store.services.kiosk import (
    UBO_WEBUI_DASHBOARD_ID,
    KioskAddDashboardAction,
    KioskApplyConfigEvent,
    KioskClearEnabledStateAction,
    KioskDashboard,
    KioskDeleteDashboardAction,
    KioskPortRole,
    KioskPortSelection,
    KioskPortSelections,
    KioskRotatePortAction,
    KioskSetPortSelectionAction,
    KioskUpdateStateAction,
)
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.utils import IS_RPI
from ubo_app.utils.apt import is_package_installed
from ubo_app.utils.async_ import create_task
from ubo_app.utils.input import ubo_input
from ubo_app.utils.menu_items import build_selection_menu
from ubo_app.utils.monitor_unit import is_unit_enabled, monitor_unit
from ubo_app.utils.persistent_store import register_persistent_store
from ubo_app.utils.server import send_command

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.store.services.kiosk import KioskState

KIOSK_HDMI_MENU_ID = 'kiosk:hdmi'
KIOSK_DASHBOARDS_MENU_ID = 'kiosk:dashboards'

# (state field name, navigation path key, DRM/Weston output name, menu label)
PORTS: tuple[tuple[str, str, str, str], ...] = (
    ('hdmi_a_1', 'hdmi-a-1', 'HDMI-A-1', 'HDMI-1'),
    ('hdmi_a_2', 'hdmi-a-2', 'HDMI-A-2', 'HDMI-2'),
)
_PORT_PATH_KEYS = {path_key for _, path_key, _, _ in PORTS}

# Action-id prefixes whose handlers depend on the (mutable) dashboard list and
# are therefore re-registered whenever dashboards change.
_DYNAMIC_ACTION_PREFIXES = (
    *(f'kiosk:set:{field_name}:dash:' for field_name, _, _, _ in PORTS),
    'kiosk:dashboard:delete:',
)

_ROLE_ICONS: dict[KioskPortRole, str] = {
    KioskPortRole.BROWSER: '󰖟',
    KioskPortRole.TERMINAL: '󰆍',
    KioskPortRole.OFF: '󰜺',
}


def _dashboard_names(dashboards: tuple[KioskDashboard, ...]) -> dict[str, str]:
    return {dashboard.id: dashboard.name for dashboard in dashboards}


def _selection_label(
    selection: KioskPortSelection,
    names: dict[str, str],
) -> str:
    """Human label for a port selection: Terminal, Off, or the dashboard name."""
    if selection.role == KioskPortRole.TERMINAL:
        return 'Terminal'
    if selection.role == KioskPortRole.OFF:
        return 'Off'
    return names.get(selection.dashboard_id or '', 'Browser')


def _current_config() -> tuple[KioskPortSelections, tuple[KioskDashboard, ...]]:
    @store.with_state(
        lambda state: (state.kiosk.port_selections, state.kiosk.dashboards),
    )
    def _get(
        data: tuple[KioskPortSelections, tuple[KioskDashboard, ...]],
    ) -> tuple[KioskPortSelections, tuple[KioskDashboard, ...]]:
        return data

    return _get()


def install_kiosk() -> None:
    """Install the kiosk packages (weston, seatd, foot, chromium)."""

    async def act() -> None:
        store.dispatch(KioskUpdateStateAction(is_installing=True))
        result = await send_command(
            'package',
            'install',
            'kiosk',
            has_output=True,
        )
        store.dispatch(KioskUpdateStateAction(is_installing=False))
        if result != 'installed':
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        title='Browser Kiosk',
                        content='Failed to install',
                        display_type=NotificationDisplayType.STICKY,
                        color=DANGER_COLOR,
                        icon='󰜺',
                        chime=Chime.FAILURE,
                    ),
                ),
            )
        await check_kiosk()

    create_task(act())


def start_kiosk_service() -> None:
    """Write the current config then start the kiosk service."""

    async def act() -> None:
        if IS_RPI:
            write_kiosk_config(*_current_config())
        await send_command('service', 'ubo-kiosk', 'start')

    create_task(act())


def stop_kiosk_service() -> None:
    """Stop the kiosk service."""
    create_task(send_command('service', 'ubo-kiosk', 'stop'))


def enable_kiosk_service() -> None:
    """Enable the kiosk service to start on boot."""

    async def act() -> None:
        store.dispatch(KioskClearEnabledStateAction())
        await send_command('service', 'ubo-kiosk', 'enable')
        await asyncio.sleep(5)
        await check_kiosk()

    create_task(act())


def disable_kiosk_service() -> None:
    """Disable the kiosk service from starting on boot."""

    async def act() -> None:
        store.dispatch(KioskClearEnabledStateAction())
        await send_command('service', 'ubo-kiosk', 'disable')
        await asyncio.sleep(5)
        await check_kiosk()

    create_task(act())


def _set_selection(
    port: str,
    role: KioskPortRole,
    dashboard_id: str | None = None,
) -> None:
    store.dispatch(
        KioskSetPortSelectionAction(port=port, role=role, dashboard_id=dashboard_id),
    )


def _rotate_port(port: str) -> None:
    store.dispatch(KioskRotatePortAction(port=port))


async def _add_dashboard() -> None:
    """Prompt for a name + URL and add the dashboard to the set."""
    with contextlib.suppress(asyncio.CancelledError):
        _, result = await ubo_input(
            prompt='Add Dashboard',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='name',
                            label='Name',
                            type=InputFieldType.TEXT,
                            description='e.g. HA Dashboard',
                            required=True,
                        ),
                        InputFieldDescription(
                            name='url',
                            label='URL',
                            type=InputFieldType.TEXT,
                            description='e.g. http://homeassistant.local:8123',
                            pattern=r'https?://.+',
                            required=True,
                        ),
                    ],
                ),
            ],
        )
        if not result:
            return
        name = (result.data.get('name', '') or '').strip()
        url = (result.data.get('url', '') or '').strip()
        if not name or not url:
            return
        store.dispatch(
            KioskAddDashboardAction(id=uuid.uuid4().hex[:8], name=name, url=url),
        )


def _start_add_dashboard() -> None:
    # Return None (not the create_task Task): the menu framework treats a
    # non-None action result plus the item's key as "push a submenu keyed by
    # the item", which would navigate into an empty ``kiosk:dashboards:add``
    # view ('Nothing here yet') instead of staying on the dashboards list.
    create_task(_add_dashboard())


def _make_delete_handler(dashboard_id: str) -> Callable[[], None]:
    def _handler() -> None:
        store.dispatch(
            StackPopAction(),
            KioskDeleteDashboardAction(dashboard_id=dashboard_id),
        )

    return _handler


def _register_kiosk_action_handlers() -> None:
    """Register the static (dashboard-independent) kiosk action handlers."""
    from ubo_app.store.core.action_registry import register_action

    register_action('kiosk:install', install_kiosk, allow_reregister=True)
    register_action('kiosk:start', start_kiosk_service, allow_reregister=True)
    register_action('kiosk:stop', stop_kiosk_service, allow_reregister=True)
    register_action('kiosk:enable', enable_kiosk_service, allow_reregister=True)
    register_action('kiosk:disable', disable_kiosk_service, allow_reregister=True)
    register_action(
        'kiosk:dashboard:add',
        _start_add_dashboard,
        allow_reregister=True,
    )

    for field_name, _path_key, _drm_name, _label in PORTS:
        register_action(
            f'kiosk:set:{field_name}:terminal',
            lambda port=field_name: _set_selection(port, KioskPortRole.TERMINAL),
            allow_reregister=True,
        )
        register_action(
            f'kiosk:set:{field_name}:off',
            lambda port=field_name: _set_selection(port, KioskPortRole.OFF),
            allow_reregister=True,
        )
        register_action(
            f'kiosk:rotate:{field_name}',
            lambda port=field_name: _rotate_port(port),
            allow_reregister=True,
        )


def _register_kiosk_bindable_actions() -> None:
    """Expose per-port dashboard rotation for binding (e.g. to IR remote keys).

    Reuses the existing ``kiosk:rotate:<port>`` menu handler via
    ``ExecuteMenuActionAction`` so a bound IR button rotates that port's
    dashboard.
    """
    for field_name, _path_key, _drm_name, label in PORTS:
        register_bindable_action(
            f'kiosk:rotate:{field_name}',
            f'Kiosk: Rotate {label}',
            lambda _ctx, field_name=field_name: ExecuteMenuActionAction(
                action_id=f'kiosk:rotate:{field_name}',
            ),
            allow_reregister=True,
        )


def _register_dashboard_action_handlers(
    dashboards: tuple[KioskDashboard, ...],
) -> None:
    """(Re)register the per-dashboard set/delete handlers when the set changes."""
    from ubo_app.store.core.action_registry import (
        get_registered_actions,
        register_action,
        unregister_action,
    )

    for action_id in get_registered_actions():
        if action_id.startswith(_DYNAMIC_ACTION_PREFIXES):
            unregister_action(action_id)

    for dashboard in dashboards:
        for field_name, _path_key, _drm_name, _label in PORTS:
            register_action(
                f'kiosk:set:{field_name}:dash:{dashboard.id}',
                lambda port=field_name, dashboard_id=dashboard.id: _set_selection(
                    port,
                    KioskPortRole.BROWSER,
                    dashboard_id,
                ),
                allow_reregister=True,
            )
        if dashboard.id != UBO_WEBUI_DASHBOARD_ID:
            register_action(
                f'kiosk:dashboard:delete:{dashboard.id}',
                _make_delete_handler(dashboard.id),
                allow_reregister=True,
            )


@store.autorun(lambda state: state.kiosk)
def update_kiosk_hdmi_menu(state: KioskState) -> None:
    """Update the Browser Kiosk HDMI dynamic menu (dumb UI architecture)."""
    items: list[MenuItemData] = []
    placeholder = ''
    heading: str | None = None
    sub_heading: str | None = None

    if state.is_installing:
        placeholder = 'Installing Browser Kiosk...'
        heading = 'Installing Browser Kiosk'
        sub_heading = 'This may take a few minutes'
    elif not state.is_installed:
        heading = 'Browser Kiosk is not installed'
        sub_heading = 'Install it to show a browser on an HDMI output'
        items.append(
            MenuItemData(
                key='kiosk:install',
                label='Install Browser Kiosk',
                icon='󰶮',
                action_id='kiosk:install',
            ),
        )
    else:
        items.append(
            MenuItemData(
                key='kiosk:toggle',
                label='Stop' if state.is_active else 'Start',
                icon='󰓛' if state.is_active else '󰐊',
                action_id='kiosk:stop' if state.is_active else 'kiosk:start',
            ),
        )

        if state.is_enabled is None:
            items.append(
                MenuItemData(key='kiosk:enabled-status', label='...', icon=''),
            )
        elif state.is_enabled:
            items.append(
                MenuItemData(
                    key='kiosk:disable',
                    label='Disable',
                    icon='󰯄',
                    action_id='kiosk:disable',
                ),
            )
        else:
            items.append(
                MenuItemData(
                    key='kiosk:enable',
                    label='Enable',
                    icon='󰯅',
                    action_id='kiosk:enable',
                ),
            )

        names = _dashboard_names(state.dashboards)
        for field_name, path_key, _drm_name, label in PORTS:
            selection = getattr(state.port_selections, field_name)
            items.append(
                MenuItemData(
                    key=path_key,
                    label=f'{label}: {_selection_label(selection, names)}',
                    icon=_ROLE_ICONS[selection.role],
                    action_id=f'menu:select:{path_key}',
                ),
            )

        items.append(
            MenuItemData(
                key='dashboards',
                label='Dashboards',
                icon='󰕮',
                action_id='menu:select:dashboards',
            ),
        )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=KIOSK_HDMI_MENU_ID,
            title='Browser Kiosk',
            heading=heading,
            sub_heading=sub_heading,
            items=tuple(items),
            placeholder=placeholder,
        ),
    )


@store.autorun(
    lambda state: (state.kiosk.port_selections, state.kiosk.dashboards),
)
def update_kiosk_port_menus(
    data: tuple[KioskPortSelections, tuple[KioskDashboard, ...]],
) -> None:
    """Build a Terminal/Off/<dashboard> selection menu for each HDMI port."""
    port_selections, dashboards = data
    for field_name, path_key, _drm_name, label in PORTS:
        selection = getattr(port_selections, field_name)
        options: list[tuple[str, str, str]] = [
            ('terminal', 'Terminal', f'kiosk:set:{field_name}:terminal'),
            ('off', 'Off', f'kiosk:set:{field_name}:off'),
            *(
                (
                    f'dash:{dashboard.id}',
                    dashboard.name,
                    f'kiosk:set:{field_name}:dash:{dashboard.id}',
                )
                for dashboard in dashboards
            ),
        ]
        if selection.role == KioskPortRole.BROWSER:
            selected_key = f'dash:{selection.dashboard_id}'
        else:
            selected_key = selection.role
        build_selection_menu(
            options=tuple(options),
            selected_key=selected_key,
            menu_id=f'{KIOSK_HDMI_MENU_ID}:{path_key}',
            title=label,
            heading=label,
            sub_heading='Select what this output shows',
        )


@store.autorun(lambda state: state.kiosk.dashboards)
def update_kiosk_dashboards_menu(dashboards: tuple[KioskDashboard, ...]) -> None:
    """Manage the dashboard set: an Add item plus one item per dashboard."""
    _register_dashboard_action_handlers(dashboards)

    items: list[MenuItemData] = [
        MenuItemData(
            key='add',
            label='Add',
            icon='󰐕',
            action_id='kiosk:dashboard:add',
        ),
    ]
    for dashboard in dashboards:
        items.append(
            MenuItemData(
                key=dashboard.id,
                label=dashboard.name,
                icon='󰖟',
                action_id=f'menu:select:{dashboard.id}',
            ),
        )
        _update_dashboard_detail_menu(dashboard)

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=KIOSK_DASHBOARDS_MENU_ID,
            title='Dashboards',
            items=tuple(items),
            placeholder='',
        ),
    )


def _update_dashboard_detail_menu(dashboard: KioskDashboard) -> None:
    """Build a per-dashboard submenu showing its URL and (if user-added) Delete."""
    if dashboard.id == UBO_WEBUI_DASHBOARD_ID:
        items: tuple[MenuItemData, ...] = ()
        placeholder = 'Built-in dashboard'
    else:
        items = (
            MenuItemData(
                key='delete',
                label='Delete',
                icon='󰆴',
                action_id=f'kiosk:dashboard:delete:{dashboard.id}',
                background_color=DANGER_COLOR,
            ),
        )
        placeholder = ''

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=f'{KIOSK_DASHBOARDS_MENU_ID}:{dashboard.id}',
            title=dashboard.name,
            heading=dashboard.name,
            sub_heading=dashboard.url,
            items=items,
            placeholder=placeholder,
        ),
    )


async def check_kiosk() -> None:
    """Refresh installed/enabled state from the system."""
    is_enabled, is_installed = await asyncio.gather(
        is_unit_enabled('ubo-kiosk'),
        is_package_installed('weston'),
    )
    store.dispatch(
        KioskUpdateStateAction(
            is_enabled=is_installed and is_enabled,
            is_installed=is_installed,
        ),
    )


async def detect_connected_ports() -> None:
    """Detect which HDMI outputs are physically connected via sysfs."""
    connected: list[str] = []
    drm_path = Path('/sys/class/drm')
    for field_name, _path_key, drm_name, _label in PORTS:
        for status_path in drm_path.glob(f'*-{drm_name}/status'):
            try:
                if status_path.read_text().strip() == 'connected':
                    connected.append(field_name)
                    break
            except OSError:
                continue
    store.dispatch(KioskUpdateStateAction(connected_ports=tuple(connected)))


async def _apply_kiosk_config(_: KioskApplyConfigEvent) -> None:
    """Write config on selection changes and restart the unit if running."""

    @store.with_state(lambda state: state.kiosk.is_active)
    def _is_active(is_active: bool) -> bool:  # noqa: FBT001
        return is_active

    if IS_RPI:
        write_kiosk_config(*_current_config())
    if _is_active():
        await send_command('service', 'ubo-kiosk', 'restart')


def init_service() -> None:
    """Initialize the Browser Kiosk service."""
    from ubo_app.store.core.view_registry import register_path_menu_matcher

    _register_kiosk_action_handlers()
    _register_kiosk_bindable_actions()

    def _kiosk_path_matcher(path: tuple[str, ...]) -> str | None:
        # Nested under Display:
        # ('main', 'settings', <category>, 'display:', 'hdmi'[, <key>[, <id>]])
        if (
            len(path) >= 5  # noqa: PLR2004
            and path[3] == 'display:'
            and path[4] == 'hdmi'
        ):
            if len(path) == 5:  # noqa: PLR2004
                return KIOSK_HDMI_MENU_ID
            if len(path) == 6:  # noqa: PLR2004
                if path[5] in _PORT_PATH_KEYS:
                    return f'{KIOSK_HDMI_MENU_ID}:{path[5]}'
                if path[5] == 'dashboards':
                    return KIOSK_DASHBOARDS_MENU_ID
            if len(path) == 7 and path[5] == 'dashboards':  # noqa: PLR2004
                return f'{KIOSK_DASHBOARDS_MENU_ID}:{path[6]}'
        return None

    register_path_menu_matcher('kiosk:hdmi', _kiosk_path_matcher)

    for field_name, _path_key, _drm_name, _label in PORTS:
        register_persistent_store(
            f'kiosk:{field_name}',
            lambda state, field_name=field_name: getattr(
                state.kiosk.port_selections,
                field_name,
            ),
        )
    register_persistent_store(
        'kiosk:dashboards',
        lambda state: tuple(
            dashboard
            for dashboard in state.kiosk.dashboards
            if dashboard.id != UBO_WEBUI_DASHBOARD_ID
        ),
    )

    store.subscribe_event(KioskApplyConfigEvent, _apply_kiosk_config)

    create_task(check_kiosk())
    create_task(detect_connected_ports())
    create_task(
        monitor_unit(
            'ubo-kiosk.service',
            lambda status: store.dispatch(
                KioskUpdateStateAction(
                    is_active=status in ('active', 'activating', 'reloading'),
                ),
            ),
        ),
    )
