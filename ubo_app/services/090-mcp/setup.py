"""Implement `init_service` for the MCP service.

Owns the MCP server domain: on-disk config CRUD, the ``state.mcp`` slice, and the
settings UI to add/enable/disable/delete servers. The aggregated, enabled set is
consumed over gRPC by the MCP gateway subprocess (``ubo-service``), which exposes
every server behind a single token-gated SSE + Streamable HTTP endpoint.
"""

from __future__ import annotations

import json
import secrets as stdlib_secrets
import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.utils.types import Subscriptions

from constants import (
    LEGACY_MCP_SERVERS_PATH,
    MCP_GATEWAY_TOKEN_SECRET_ID,
    MCP_SERVERS_PATH,
)
from redux import AutorunOptions

from ubo_app.colors import DANGER_COLOR, INFO_COLOR, WARNING_COLOR
from ubo_app.constants import MCP_GATEWAY_LISTEN_PORT
from ubo_app.logger import logger
from ubo_app.store.core.action_registry import register_action, unregister_action
from ubo_app.store.core.types import (
    MenuGoBackAction,
    MenuItemData,
    RegisterSettingAppAction,
    SettingsCategory,
    StackPushMenuAction,
    UpdateDynamicMenuAction,
)
from ubo_app.store.core.view_registry import (
    register_menu_content_dependency,
    register_path_menu_matcher,
)
from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    WebUIInputDescription,
)
from ubo_app.store.main import store
from ubo_app.store.services.mcp import (
    McpAddServerEvent,
    McpDeleteServerEvent,
    McpServerMetadata,
    McpServerType,
    McpSetServersAction,
    McpSyncServersAction,
    McpSyncServersEvent,
    McpToggleServerEvent,
)
from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.utils.async_ import create_task
from ubo_app.utils.input import ubo_input
from ubo_app.utils.persistent_store import register_persistent_store
from ubo_app.utils.secrets import read_secret, write_secret


def _migrate_legacy_servers() -> None:
    """Move the old ``assistant_mcp_servers`` directory to ``mcp_servers`` once.

    The MCP config used to live under the assistant. If the new location does
    not yet exist but the old one does, relocate it so previously-configured
    servers (and their per-server ``enabled`` flags) survive the rename.
    """
    if LEGACY_MCP_SERVERS_PATH.exists() and not MCP_SERVERS_PATH.exists():
        logger.info(
            'Migrating legacy MCP servers directory',
            extra={'from': str(LEGACY_MCP_SERVERS_PATH), 'to': str(MCP_SERVERS_PATH)},
        )
        shutil.move(str(LEGACY_MCP_SERVERS_PATH), str(MCP_SERVERS_PATH))
        # `shutil.move` preserves the old (world-readable) permissions, so harden
        # the migrated tree in place: configs can carry per-server secrets
        # (StdioMcpConfig.env). Mirrors ubo_app/utils/secrets.py.
        MCP_SERVERS_PATH.chmod(0o700)
        for server_dir in MCP_SERVERS_PATH.iterdir():
            if not server_dir.is_dir():
                continue
            server_dir.chmod(0o700)
            config_file = server_dir / 'config.json'
            if config_file.exists():
                config_file.chmod(0o600)


def _ensure_gateway_token() -> None:
    """Generate the gateway bearer token on first run if it is not set yet."""
    if not read_secret(MCP_GATEWAY_TOKEN_SECRET_ID):
        write_secret(
            key=MCP_GATEWAY_TOKEN_SECRET_ID,
            value=stdlib_secrets.token_urlsafe(32),
        )
        logger.info('Generated MCP gateway bearer token')


def _show_gateway_token() -> None:
    """Reveal the gateway bearer token and endpoint URLs in a notification.

    Lets the user connect an off-device MCP client (e.g. Claude Desktop) without
    SSHing in to read the secrets file. Mirrors the OpenClaw "Show gateway token"
    pattern. Returns None (a non-None result would push a stray menu frame).
    """
    token = read_secret(MCP_GATEWAY_TOKEN_SECRET_ID)
    if not token:
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id='mcp:gateway_token',
                    title='MCP gateway token',
                    content='No gateway token is set yet.',
                    icon='󰒋',
                    importance=Importance.LOW,
                ),
            ),
        )
        return

    # The token is shown in full on purpose: the user has to copy it into an
    # off-device MCP client, so masking it (e.g. `***last4`) would defeat the
    # feature. While the notification is open the raw token lives in
    # `state.notifications`, but `dismiss_on_close=True` removes it from state
    # the moment the user closes it, and the notifications slice is runtime-only
    # (not among the registered persistent stores), so the token is never
    # written to `state.json` on disk.
    #
    # `{{hostname}}` is replaced with `<hostname>.local` by
    # Notification.__post_init__ — but only in title/content, so the endpoint
    # URLs must live in `content` (not `extra_information`).
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id='mcp:gateway_token',
                title='MCP gateway token',
                content=(
                    f'Token: {token}\n\n'
                    f'Streamable HTTP: http://{{{{hostname}}}}:{MCP_GATEWAY_LISTEN_PORT}/mcp\n'
                    f'SSE: http://{{{{hostname}}}}:{MCP_GATEWAY_LISTEN_PORT}/sse\n\n'
                    'Auth header: Authorization: Bearer <token>'
                ),
                icon='󰒋',
                importance=Importance.MEDIUM,
                display_type=NotificationDisplayType.STICKY,
                show_dismiss_action=True,
                dismiss_on_close=True,
                extra_information=ReadableInformation(
                    text='Add this endpoint and bearer token to an MCP client '
                    'such as Claude Desktop to use the aggregated tools from '
                    'off-device.',
                ),
            ),
        ),
    )


def input_mcp_server() -> None:
    """Input MCP server configuration via WebUI."""

    async def act() -> None:
        import asyncio
        import contextlib

        from mcp_servers import validate_sse_url, validate_stdio_config

        from ubo_app.store.services.mcp import (
            McpAddServerAction,
            SseMcpConfig,
            StdioMcpConfig,
        )

        with contextlib.suppress(asyncio.CancelledError):
            _, result = await ubo_input(
                prompt='Add MCP Server',
                descriptions=[
                    WebUIInputDescription(
                        fields=[
                            InputFieldDescription(
                                name='name',
                                label='Server Name',
                                type=InputFieldType.TEXT,
                                description='Friendly name for this MCP server',
                                required=True,
                            ),
                            InputFieldDescription(
                                name='type',
                                label='Server Type',
                                type=InputFieldType.SELECT,
                                description='Type of MCP server',
                                options=['stdio', 'sse'],
                                required=True,
                            ),
                            InputFieldDescription(
                                name='config',
                                label='Configuration',
                                type=InputFieldType.LONG,
                                description='For stdio: paste full JSON with '
                                'mcpServers. For sse: paste URL',
                                required=True,
                            ),
                        ],
                    ),
                ],
            )

            if not result or not result.data:
                return

            name = result.data.get('name', '').strip()
            server_type_str = result.data.get('type', '').strip()
            config_str = result.data.get('config', '').strip()

            if not name or not server_type_str or not config_str:
                return

            server_type = McpServerType(server_type_str)

            # Validate and create typed configuration
            if server_type == McpServerType.STDIO:
                is_valid, error_msg, parsed_config = validate_stdio_config(config_str)
                if not is_valid or not parsed_config:
                    logger.error(
                        'Invalid stdio configuration',
                        extra={'error': error_msg},
                    )
                    return
                # Extract server config and create typed object
                mcp_servers_dict = parsed_config.get('mcpServers', {})
                server_config = next(iter(mcp_servers_dict.values()))
                typed_config: StdioMcpConfig | SseMcpConfig = StdioMcpConfig(
                    command=server_config['command'],
                    args=server_config.get('args', []),
                    env=server_config.get('env', {}),
                )
            else:  # SSE
                is_valid, error_msg = validate_sse_url(config_str)
                if not is_valid:
                    logger.error('Invalid SSE URL', extra={'error': error_msg})
                    return
                typed_config = SseMcpConfig(url=config_str)

            # Dispatch the add action; the reducer emits McpAddServerEvent and
            # handle_add_mcp_server persists it to disk (single write path,
            # shared with non-UI/gRPC dispatchers).
            store.dispatch(
                McpAddServerAction(
                    name=name,
                    type=server_type,
                    config=typed_config,
                ),
            )

            logger.info('MCP server add dispatched', extra={'server_name': name})

    create_task(act())


def _register_persistent_stores() -> None:
    """Register persistent stores for the MCP service."""
    register_persistent_store(
        'mcp:enabled_mcp_servers',
        lambda state: json.dumps(list(state.mcp.enabled_mcp_servers)),
    )


def _register_path_matcher() -> Callable[[], None]:
    """Register path matcher for MCP settings sub-pages."""

    def _mcp_path_matcher(path: tuple[str, ...]) -> str | None:
        # Paths like ('main', 'settings', 'Assistant', 'mcp:tools', ['{server_id}'])
        if (
            len(path) >= 4  # noqa: PLR2004
            and path[:3] == ('main', 'settings', SettingsCategory.ASSISTANT.value)
        ):
            menu_key = path[3]
            # Per-server detail page must be checked BEFORE the list, otherwise
            # the list menu key matches first and the detail page is never
            # reached. The server id is the trailing path segment.
            if len(path) >= 5 and menu_key == 'mcp:tools':  # noqa: PLR2004
                server_id = path[4]
                return f'mcp:server:{server_id}'
            if menu_key == 'mcp:tools':
                return 'mcp:tools'
        return None

    return register_path_menu_matcher('mcp:menus', _mcp_path_matcher)


async def init_service() -> Subscriptions:  # noqa: C901, PLR0915
    """Initialize the MCP service."""
    _migrate_legacy_servers()
    _ensure_gateway_token()
    _register_persistent_stores()

    # Menu content dependencies so the visible MCP menus recompute when the
    # enabled set or the configured-server set changes.
    unregister_enabled_dependency = register_menu_content_dependency(
        'mcp:enabled',
        lambda s: tuple(s.mcp.enabled_mcp_servers),
    )
    unregister_servers_dependency = register_menu_content_dependency(
        'mcp:servers',
        lambda s: tuple(s.mcp.mcp_servers.keys()),
    )

    _mcp_action_ids: list[str] = []
    _mcp_server_unsubscribers: dict[str, Callable] = {}

    def mcp_server_menu(server_id: str) -> Callable:
        """Set up dynamic menu updates for a specific MCP server."""
        from ubo_app.store.services.mcp import (
            McpDeleteServerAction,
            McpToggleServerAction,
        )

        _server_action_ids: list[str] = []

        @store.autorun(
            lambda state: (
                state.mcp.mcp_servers.get(server_id),
                server_id in state.mcp.enabled_mcp_servers,
            ),
            options=AutorunOptions(default_value=None),
        )
        def menu(
            state_data: tuple[McpServerMetadata | None, bool],
        ) -> None:
            server, is_enabled = state_data

            for action_id in _server_action_ids:
                unregister_action(action_id)
            _server_action_ids.clear()

            if not server:
                store.dispatch(
                    UpdateDynamicMenuAction(
                        menu_id=f'mcp:server:{server_id}',
                        title='MCP Server',
                        items=(),
                        heading='Server Not Found',
                    ),
                )
                return

            toggle_action_id = f'mcp:toggle:{server_id}'
            _server_action_ids.append(toggle_action_id)
            register_action(
                toggle_action_id,
                lambda: store.dispatch(
                    McpToggleServerAction(server_id=server_id),
                ),
            )

            delete_action_id = f'mcp:delete:{server_id}'
            _server_action_ids.append(delete_action_id)
            register_action(
                delete_action_id,
                lambda: store.dispatch(
                    McpDeleteServerAction(server_id=server_id),
                ),
            )

            status_text = 'Enabled' if is_enabled else 'Disabled'
            items = (
                MenuItemData(
                    key='toggle',
                    label='Disable' if is_enabled else 'Enable',
                    icon='󰖭' if is_enabled else '󰄬',
                    background_color=WARNING_COLOR if is_enabled else INFO_COLOR,
                    action_id=toggle_action_id,
                ),
                MenuItemData(
                    key='delete',
                    label='Delete',
                    icon='󰆴',
                    background_color=DANGER_COLOR,
                    action_id=delete_action_id,
                ),
            )

            store.dispatch(
                UpdateDynamicMenuAction(
                    menu_id=f'mcp:server:{server_id}',
                    title=f'MCP: {server.name}',
                    items=items,
                    heading=server.name,
                    sub_heading=f'Type: {server.type} • {status_text}',
                ),
            )

        def cleanup() -> None:
            # Stopping the autorun alone would leave the last-registered toggle/
            # delete action ids dangling, so unregister them too.
            for action_id in _server_action_ids:
                unregister_action(action_id)
            _server_action_ids.clear()
            menu.unsubscribe()

        return cleanup

    # MCP Tools menu - main list
    @store.autorun(
        lambda state: (
            state.mcp.mcp_servers,
            state.mcp.enabled_mcp_servers,
        ),
    )
    def mcp_servers_menu(
        state_data: tuple[dict[str, McpServerMetadata], list[str]],
    ) -> None:
        """Update dynamic menu for MCP servers."""
        loaded_servers, enabled_servers = state_data

        for action_id in _mcp_action_ids:
            unregister_action(action_id)
        _mcp_action_ids.clear()

        logger.debug(
            'MCP servers menu autorun triggered',
            extra={
                'server_count': len(loaded_servers),
                'server_ids': list(loaded_servers.keys()),
                'enabled_count': len(enabled_servers),
            },
        )

        add_action_id = 'mcp:add-server'
        _mcp_action_ids.append(add_action_id)
        register_action(add_action_id, input_mcp_server)

        show_token_action_id = 'mcp:show-gateway-token'  # noqa: S105
        _mcp_action_ids.append(show_token_action_id)
        register_action(show_token_action_id, _show_gateway_token)

        items: list[MenuItemData] = [
            MenuItemData(
                key='add_server',
                label='Add Server',
                icon='󰌉',
                action_id=add_action_id,
            ),
            MenuItemData(
                key='show_gateway_token',
                label='Show gateway token',
                icon='󰌋',
                action_id=show_token_action_id,
            ),
        ]

        # Clean up autoruns for servers no longer in the list
        removed_ids = set(_mcp_server_unsubscribers.keys()) - set(
            loaded_servers.keys(),
        )
        for removed_id in removed_ids:
            _mcp_server_unsubscribers.pop(removed_id)()

        for server_id, server in loaded_servers.items():
            is_enabled = server_id in enabled_servers
            open_action_id = f'mcp:open:{server_id}'
            _mcp_action_ids.append(open_action_id)
            register_action(
                open_action_id,
                lambda _sid=server_id: store.dispatch(
                    StackPushMenuAction(menu_key=_sid),
                ),
            )
            items.append(
                MenuItemData(
                    key=server_id,
                    label=server.name,
                    icon='󰄬' if is_enabled else '󰖭',
                    background_color=INFO_COLOR if is_enabled else WARNING_COLOR,
                    action_id=open_action_id,
                ),
            )

            # Set up the detail menu for this server (only if not already tracked)
            if server_id not in _mcp_server_unsubscribers:
                _mcp_server_unsubscribers[server_id] = mcp_server_menu(server_id)

        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id='mcp:tools',
                title='MCP Tools',
                heading='Model Context Protocol Tools',
                sub_heading='Add and manage MCP servers',
                items=tuple(items),
            ),
        )

    # Event handlers for MCP servers
    def handle_add_mcp_server(event: McpAddServerEvent) -> None:
        """Persist a newly added MCP server, then sync state from disk.

        This is the single write path for adds: the UI and any remote (gRPC)
        dispatcher of ``McpAddServerAction`` both land here via the reducer's
        ``McpAddServerEvent``, mirroring the delete/toggle handlers.
        """
        from mcp_servers import save_mcp_server

        logger.info(
            'handle_add_mcp_server invoked',
            extra={'server_name': event.name},
        )
        save_mcp_server(event.name, event.type, event.config)
        store.dispatch(McpSyncServersAction())

    def handle_delete_mcp_server(event: McpDeleteServerEvent) -> None:
        """Handle MCP server delete event."""
        from mcp_servers import delete_mcp_server

        logger.info(
            'handle_delete_mcp_server invoked',
            extra={'server_id': event.server_id},
        )
        delete_mcp_server(event.server_id)
        # Navigate back to server list
        store.dispatch(MenuGoBackAction())
        # Trigger sync to update state
        logger.info('Dispatching McpSyncServersAction after delete')
        store.dispatch(McpSyncServersAction())

    def handle_toggle_mcp_server(event: McpToggleServerEvent) -> None:
        """Persist the toggled MCP server enabled state to the filesystem."""
        from mcp_servers import toggle_mcp_server

        logger.info(
            'handle_toggle_mcp_server invoked',
            extra={'server_id': event.server_id},
        )
        toggle_mcp_server(event.server_id)

    def handle_sync_mcp_servers(_event: McpSyncServersEvent) -> None:
        """Load MCP servers from the filesystem and push them into the store."""
        from mcp_servers import load_enabled_mcp_server_ids, load_mcp_servers

        servers = load_mcp_servers()
        enabled = load_enabled_mcp_server_ids()
        logger.info(
            'handle_sync_mcp_servers loaded servers',
            extra={'count': len(servers), 'enabled': len(enabled)},
        )
        store.dispatch(
            McpSetServersAction(
                servers=list(servers.values()),
                enabled_servers=enabled,
            ),
        )

    store.dispatch(
        RegisterSettingAppAction(
            category=SettingsCategory.ASSISTANT,
            priority=15,
            key='tools',
            label='MCP Tools',
            icon='󰒋',
        ),
    )

    unregister_path_matcher = _register_path_matcher()

    subscriptions = [
        store.subscribe_event(McpAddServerEvent, handle_add_mcp_server),
        store.subscribe_event(McpDeleteServerEvent, handle_delete_mcp_server),
        store.subscribe_event(McpToggleServerEvent, handle_toggle_mcp_server),
        store.subscribe_event(McpSyncServersEvent, handle_sync_mcp_servers),
    ]

    store.dispatch(McpSyncServersAction())

    def cleanup_dynamic_menus() -> None:
        # Per-item action ids are diffed/re-registered each autorun pass, so on
        # teardown they would otherwise leak. Unregister the top-level ids and
        # tear down every per-server detail autorun (which also clears its own
        # toggle/delete ids — see mcp_server_menu.cleanup).
        for action_id in _mcp_action_ids:
            unregister_action(action_id)
        _mcp_action_ids.clear()
        for unsubscribe in _mcp_server_unsubscribers.values():
            unsubscribe()
        _mcp_server_unsubscribers.clear()

    return [
        *subscriptions,
        unregister_enabled_dependency,
        unregister_servers_dependency,
        unregister_path_matcher,
        mcp_servers_menu.unsubscribe,
        cleanup_dynamic_menus,
    ]
