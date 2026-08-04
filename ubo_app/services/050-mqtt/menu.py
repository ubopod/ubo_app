"""The MQTT settings menu.

Two broker modes are configurable here, and they are genuinely different
deployments rather than a preference:

* ``BUNDLED`` — the Mosquitto container in the on-device Home Assistant
  composition, reached on the host's loopback. Needs no configuration.
* ``EXTERNAL`` — Home Assistant on another machine on the LAN, with its own
  broker. Needs a host, and usually credentials.

Until this menu existed ``EXTERNAL`` was modelled in the store but unreachable,
because nothing could enter a host or a password.

The password is written to the secrets file, never to the store — the store only
remembers *that* there is one (``MqttBrokerConfig.has_password``).
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

from constants import (
    LOOPBACK_HOSTS,
    MQTT_BROKER_MENU_ID,
    MQTT_PASSWORD_SECRET_ID,
    MQTT_SETTINGS_MENU_ID,
)

from ubo_app.colors import DANGER_COLOR, SUCCESS_COLOR, WARNING_COLOR
from ubo_app.store.core.action_registry import register_action, unregister_action
from ubo_app.store.core.types import (
    MenuItemData,
    OpenRenderAction,
    RegisterSettingAppAction,
    SettingsCategory,
    StackPushMenuAction,
    UpdateDynamicMenuAction,
)
from ubo_app.store.core.view_registry import register_path_menu_matcher
from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    WebUIInputDescription,
)
from ubo_app.store.main import store
from ubo_app.store.services.mqtt import (
    DEFAULT_PORT,
    DEFAULT_TLS_PORT,
    MqttBrokerConfig,
    MqttBrokerSource,
    MqttConnectionStatus,
    MqttSetAllowRemoteControlAction,
    MqttSetBrokerAction,
    MqttSetEnabledAction,
)
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.utils.async_ import create_task
from ubo_app.utils.input import ubo_input
from ubo_app.utils.menu_items import build_selection_menu
from ubo_app.utils.secrets import clear_secret, write_secret

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

TEST_NOTIFICATION_ID = 'mqtt_test'
_SETTINGS_PATH_LENGTH = 4
_BROKER_PATH_LENGTH = 5
_SETTINGS_PATH_KEY = 'mqtt:'

_STATUS_LABELS = {
    MqttConnectionStatus.DISABLED: 'Idle',
    MqttConnectionStatus.CONNECTING: 'Connecting',
    MqttConnectionStatus.CONNECTED: 'Connected',
    MqttConnectionStatus.ERROR: 'Error',
}
_STATUS_ICONS = {
    MqttConnectionStatus.DISABLED: '󰤭',
    MqttConnectionStatus.CONNECTING: '󰤨',
    MqttConnectionStatus.CONNECTED: '󰄬',
    MqttConnectionStatus.ERROR: '󰜺',
}


def resolve_password(
    data: Mapping[str, str],
    *,
    had_password: bool,
) -> tuple[str | None, bool]:
    """Decide what to do with the password field of a submitted broker form.

    Returns ``(secret_to_write_or_None, has_password)``. Blank does **not** mean
    "clear it": the field is never prefilled with the real secret, so a user who
    only wanted to change the host would otherwise wipe their password by
    leaving it alone. Clearing is therefore an explicit checkbox.
    """
    if _is_checkbox_on(data.get('clear_password')):
        return None, False
    password = (data.get('password') or '').strip()
    if password:
        return password, True
    return None, had_password


def _is_checkbox_on(value: str | None) -> bool:
    """Interpret a CHECKBOX form value. The web UI submits ``on``."""
    return (value or '').strip().lower() in ('on', 'true', '1', 'yes', 'checked')


def _path_matcher(path: tuple[str, ...]) -> str | None:
    """Resolve the MQTT settings pages.

    The broker-source submenu is one level deeper than the settings page, so it
    has to be checked first — otherwise the settings page matches and the
    submenu is never reachable.
    """
    if len(path) < _SETTINGS_PATH_LENGTH or path[3] != _SETTINGS_PATH_KEY:
        return None
    if len(path) >= _BROKER_PATH_LENGTH and path[4] == MQTT_BROKER_MENU_ID:
        return MQTT_BROKER_MENU_ID
    return MQTT_SETTINGS_MENU_ID


def _describe_broker(broker: MqttBrokerConfig) -> str:
    """One line naming what the bridge is pointed at."""
    if broker.source is MqttBrokerSource.BUNDLED:
        return 'Bundled broker'
    host = f'{broker.host}:{broker.port}'
    return f'{broker.username}@{host}' if broker.username else host


def _notify(*, title: str, content: str, ok: bool) -> None:
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=TEST_NOTIFICATION_ID,
                title=title,
                content=content,
                display_type=NotificationDisplayType.FLASH
                if ok
                else NotificationDisplayType.STICKY,
                color=SUCCESS_COLOR if ok else DANGER_COLOR,
                icon='󰄬' if ok else '󰜺',
                chime=Chime.DONE if ok else Chime.FAILURE,
            ),
        ),
    )


@store.with_state(lambda state: state.mqtt.is_enabled)
def _toggle_enabled(is_enabled: bool) -> None:  # noqa: FBT001
    store.dispatch(MqttSetEnabledAction(is_enabled=not is_enabled))


@store.with_state(lambda state: state.mqtt.allow_remote_control)
def _toggle_control(allow_remote_control: bool) -> None:  # noqa: FBT001
    store.dispatch(
        MqttSetAllowRemoteControlAction(
            allow_remote_control=not allow_remote_control,
        ),
    )


@store.with_state(lambda state: state.mqtt.broker)
def _select_source(broker: MqttBrokerConfig, source: MqttBrokerSource) -> None:
    if broker.source is source:
        return
    # Switching to bundled resets every external field: a bundled broker is the
    # loopback Mosquitto by definition, and leaving a stale host behind would
    # let "bundled" point somewhere else. `_parse_broker` enforces the same
    # thing on the way back in.
    store.dispatch(
        MqttSetBrokerAction(
            broker=MqttBrokerConfig()
            if source is MqttBrokerSource.BUNDLED
            else replace(broker, source=source),
        ),
    )


@store.with_state(lambda state: state.mqtt.broker)
def _open_source_menu(broker: MqttBrokerConfig) -> None:
    build_selection_menu(
        options=[
            (
                MqttBrokerSource.BUNDLED.value,
                'On this device',
                'mqtt:source:bundled',
            ),
            (
                MqttBrokerSource.EXTERNAL.value,
                'On the network',
                'mqtt:source:external',
            ),
        ],
        selected_key=broker.source.value,
        menu_id=MQTT_BROKER_MENU_ID,
        title='Broker',
        heading='Home Assistant',
        sub_heading='Where the broker runs',
    )
    store.dispatch(StackPushMenuAction(menu_key=MQTT_BROKER_MENU_ID))


async def _configure_broker() -> None:
    """Collect the external broker's address and credentials."""
    broker = _current_broker()
    try:
        _, result = await ubo_input(
            prompt='MQTT broker',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='host',
                            label='Host',
                            type=InputFieldType.TEXT,
                            description="The machine running Home Assistant's broker",
                            default_value=broker.host,
                            required=True,
                        ),
                        InputFieldDescription(
                            name='port',
                            label='Port',
                            type=InputFieldType.NUMBER,
                            default_value=str(broker.port),
                            required=True,
                        ),
                        InputFieldDescription(
                            name='username',
                            label='Username',
                            type=InputFieldType.TEXT,
                            default_value=broker.username,
                        ),
                        InputFieldDescription(
                            name='password',
                            label='Password',
                            type=InputFieldType.PASSWORD,
                            # Never prefilled with the real secret — and not
                            # even a covered form of it: this description
                            # reaches the plain-HTTP web UI.
                            description='Current: <Set> — leave blank to keep'
                            if broker.has_password
                            else 'Leave blank for an anonymous broker',
                        ),
                        InputFieldDescription(
                            name='clear_password',
                            label='Forget the stored password',
                            type=InputFieldType.CHECKBOX,
                        ),
                        InputFieldDescription(
                            name='use_tls',
                            label='Use TLS',
                            type=InputFieldType.CHECKBOX,
                            default_value='on' if broker.use_tls else '',
                        ),
                        InputFieldDescription(
                            name='ca_cert_path',
                            label='CA certificate path',
                            type=InputFieldType.TEXT,
                            description='Only for a broker with a private CA',
                            default_value=broker.ca_cert_path,
                        ),
                    ],
                ),
            ],
        )
    except asyncio.CancelledError:
        return
    if not result:
        return

    _apply_broker_form(result.data, broker)


def _apply_broker_form(data: Mapping[str, str], broker: MqttBrokerConfig) -> None:
    """Validate a submitted broker form and store it."""
    host = (data.get('host') or '').strip()
    if not host:
        _notify(title='MQTT', content='A host is required.', ok=False)
        return

    use_tls = _is_checkbox_on(data.get('use_tls'))
    try:
        port = int((data.get('port') or '').strip())
    except ValueError:
        port = DEFAULT_TLS_PORT if use_tls else DEFAULT_PORT
    if not 1 <= port <= 65535:  # noqa: PLR2004
        _notify(title='MQTT', content=f'{port} is not a valid port.', ok=False)
        return

    password, has_password = resolve_password(
        data,
        had_password=broker.has_password,
    )
    if password is not None:
        write_secret(key=MQTT_PASSWORD_SECRET_ID, value=password)
    elif not has_password and broker.has_password:
        clear_secret(MQTT_PASSWORD_SECRET_ID)
    if password is not None or (not has_password and broker.has_password):
        # A password-only change leaves the broker config equal, so the
        # settings autorun never fires — the supervisor caches the resolved
        # password and has to be told the secret moved under it.
        from client import request_reconnect

        request_reconnect()

    store.dispatch(
        MqttSetBrokerAction(
            broker=MqttBrokerConfig(
                source=MqttBrokerSource.EXTERNAL,
                host=host,
                port=port,
                username=(data.get('username') or '').strip(),
                has_password=has_password,
                use_tls=use_tls,
                ca_cert_path=(data.get('ca_cert_path') or '').strip(),
            ),
        ),
    )

    if has_password and not use_tls and host not in LOOPBACK_HOSTS:
        # Accepted, not refused — a trusted LAN is a legitimate deployment —
        # but said out loud: port 1883 without TLS sends the password in the
        # clear on every connect.
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id='mqtt:plaintext',
                    title='MQTT',
                    content='TLS is off — the password will cross the network '
                    'unencrypted.',
                    display_type=NotificationDisplayType.STICKY,
                    color=WARNING_COLOR,
                    icon='󰀦',
                ),
            ),
        )


@store.with_state(lambda state: state.mqtt.broker)
def _current_broker(broker: MqttBrokerConfig) -> MqttBrokerConfig:
    return broker


# Whether a "Test Connection" probe is already running; see
# `_start_test_connection`.
_is_probing = False


async def _test_connection() -> None:
    """Open a throwaway session so a bad host or password says so out loud."""
    global _is_probing  # noqa: PLW0603
    from client import probe

    try:
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id=TEST_NOTIFICATION_ID,
                    title='MQTT',
                    content='Connecting to the broker ...',
                    display_type=NotificationDisplayType.STICKY,
                    color=WARNING_COLOR,
                    icon='󰝔',
                    show_dismiss_action=False,
                ),
            ),
        )

        error = await probe()
        if error is None:
            _notify(title='MQTT', content='Connected to the broker.', ok=True)
        else:
            _notify(title='MQTT', content=error, ok=False)
    finally:
        _is_probing = False


@store.with_state(lambda state: (state.mqtt.status, state.mqtt.last_error))
def _open_status(data: tuple[MqttConnectionStatus, str | None]) -> None:
    status, last_error = data
    store.dispatch(
        OpenRenderAction(
            kind='status',
            title='MQTT',
            props={
                'icon': _STATUS_ICONS.get(status, '󰋗'),
                'text': last_error or _STATUS_LABELS.get(status, 'Unknown'),
            },
        ),
    )


def _update_menu(
    data: tuple[
        bool,
        MqttConnectionStatus,
        str | None,
        MqttBrokerConfig,
        bool,
    ],
) -> None:
    """Render the MQTT settings page."""
    is_enabled, status, last_error, broker, allow_remote_control = data

    items = [
        MenuItemData(
            key='mqtt:toggle',
            label=f'MQTT: {"On" if is_enabled else "Off"}',
            icon='󰄬' if is_enabled else '󰜺',
            action_id='mqtt:toggle',
        ),
        MenuItemData(
            key='mqtt:source',
            label='On this device'
            if broker.source is MqttBrokerSource.BUNDLED
            else 'On the network',
            icon='󰋊' if broker.source is MqttBrokerSource.BUNDLED else '󰩟',
            action_id='mqtt:source',
        ),
    ]

    if broker.source is MqttBrokerSource.EXTERNAL:
        items.append(
            MenuItemData(
                key='mqtt:configure',
                label='Broker Settings',
                icon='󰢻',
                action_id='mqtt:configure',
            ),
        )

    items.extend(
        [
            MenuItemData(
                key='mqtt:status',
                label=f'Status: {_STATUS_LABELS.get(status, "Unknown")}',
                icon=_STATUS_ICONS.get(status, '󰋗'),
                action_id='mqtt:status',
            ),
            MenuItemData(
                key='mqtt:test',
                label='Test Connection',
                icon='󰑓',
                action_id='mqtt:test',
            ),
            MenuItemData(
                key='mqtt:control',
                label=f'HA Control: {"On" if allow_remote_control else "Off"}',
                icon='󰐾' if allow_remote_control else '󰜺',
                action_id='mqtt:control',
            ),
        ],
    )

    # The bundled broker is anonymous by design, and so is many a home LAN
    # broker. Say so where the user turns inbound control on, not only in the
    # README — a toggle is not an authentication boundary.
    sub_heading = _describe_broker(broker)
    if allow_remote_control and not broker.username:
        sub_heading = '󰀦 Broker has no credentials'
    elif last_error and status is MqttConnectionStatus.ERROR:
        sub_heading = f'󰜺 {last_error}'

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=MQTT_SETTINGS_MENU_ID,
            title='MQTT',
            heading='MQTT',
            sub_heading=sub_heading,
            items=tuple(items),
            placeholder='',
        ),
    )


def _select_bundled() -> None:
    _select_source(MqttBrokerSource.BUNDLED)


def _select_external() -> None:
    _select_source(MqttBrokerSource.EXTERNAL)


# These two launch a task and return None on purpose: a truthy return from
# `execute_action` is read as "push a submenu", which would leave a stray empty
# page on the stack.
def _start_configure_broker() -> None:
    create_task(_configure_broker())


def _start_test_connection() -> None:
    global _is_probing  # noqa: PLW0603
    # One probe at a time: each press would otherwise open another concurrent
    # 10 s session, all writing over the same notification.
    if _is_probing:
        return
    _is_probing = True
    create_task(_test_connection())


def init_menu() -> list[Callable[[], None]]:
    """Register the MQTT settings app, its actions and its path matcher."""
    store.dispatch(
        RegisterSettingAppAction(
            # Sorted descending, so this sits below WiFi and IP Addresses —
            # network *connectivity* is what a user opens this category for.
            # Negative rather than zero so an item registered without a
            # priority still lands above it.
            priority=-1,
            category=SettingsCategory.NETWORK,
            label='MQTT',
            icon='󰵁',
        ),
    )

    handlers: tuple[tuple[str, Callable[..., object]], ...] = (
        ('mqtt:toggle', _toggle_enabled),
        ('mqtt:control', _toggle_control),
        ('mqtt:source', _open_source_menu),
        ('mqtt:source:bundled', _select_bundled),
        ('mqtt:source:external', _select_external),
        ('mqtt:configure', _start_configure_broker),
        ('mqtt:test', _start_test_connection),
        ('mqtt:status', _open_status),
    )
    for action_id, handler in handlers:
        register_action(action_id, handler, allow_reregister=True)

    def _unregister_actions() -> None:
        """Drop every action this module owns.

        A stopped service that leaves these behind has handlers dispatching
        into reducers that no longer exist.
        """
        for action_id, _ in handlers:
            unregister_action(action_id)

    # Subscribed here rather than at import: a module-level `@store.autorun`
    # registers a listener the moment the file is imported.
    menu = store.autorun(
        lambda state: (
            state.mqtt.is_enabled,
            state.mqtt.status,
            state.mqtt.last_error,
            state.mqtt.broker,
            state.mqtt.allow_remote_control,
        ),
    )(_update_menu)

    return [
        register_path_menu_matcher('mqtt:menus', _path_matcher),
        _unregister_actions,
        menu.unsubscribe,
    ]
