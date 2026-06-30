"""MCP server storage and management utilities."""

from __future__ import annotations

import json
import logging
import re
import shutil
import uuid
from typing import TYPE_CHECKING

from constants import MCP_SERVERS_PATH

from ubo_app.store.services.mcp import (
    McpServerMetadata,
    McpServerType,
    SseMcpConfig,
    StdioMcpConfig,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

logger = logging.getLogger(__name__)


def _slugify(name: str) -> str:
    """Reduce a display name to a filesystem-safe slug.

    Mirrors the slug+uuid id pattern used by the docker service
    (``080-docker/setup.py::_slugify``) so a user-controlled name can never
    introduce path separators or ``..`` into a server id.
    """
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_') or 'server'


def _resolve_server_dir(server_id: str) -> Path:
    """Resolve a server id to its directory, confined under ``MCP_SERVERS_PATH``.

    Defense-in-depth against path traversal: even if a malformed id reaches us
    from state or a legacy on-disk directory, any path that escapes the MCP
    config directory is refused before any filesystem mutation.

    Raises:
        ValueError: If ``server_id`` resolves outside ``MCP_SERVERS_PATH``.

    """
    base = MCP_SERVERS_PATH.resolve()
    server_dir = (MCP_SERVERS_PATH / server_id).resolve()
    if not server_dir.is_relative_to(base):
        msg = f'Refusing MCP server path outside the config directory: {server_id!r}'
        raise ValueError(msg)
    return server_dir


def load_mcp_servers() -> dict[str, McpServerMetadata]:
    """Load all MCP servers from filesystem.

    Returns:
        Dictionary mapping server_id to McpServerMetadata

    """
    servers: dict[str, McpServerMetadata] = {}

    if not MCP_SERVERS_PATH.exists():
        MCP_SERVERS_PATH.mkdir(parents=True, exist_ok=True)
        # Configs can carry per-server secrets (StdioMcpConfig.env), so keep the
        # container directory owner-only. Mirrors ubo_app/utils/secrets.py.
        MCP_SERVERS_PATH.chmod(0o700)
        return servers

    for server_dir in MCP_SERVERS_PATH.iterdir():
        if not server_dir.is_dir():
            continue

        config_file = server_dir / 'config.json'
        if not config_file.exists():
            logger.warning(
                'MCP server directory missing config.json',
                extra={'server_dir': server_dir.name},
            )
            continue

        try:
            with config_file.open() as f:
                data = json.load(f)

            server_type = McpServerType(data['type'])
            raw_config = data['config']

            server_id = server_dir.name
            # Prefer the persisted friendly name; fall back to parsing the
            # directory name (format: {name}_{uuid}) for legacy configs that
            # predate the stored ``name`` field.
            name = data.get('name')
            if not name:
                name_parts = server_id.rsplit('_', 1)
                name = name_parts[0] if len(name_parts) == 2 else server_id  # noqa: PLR2004

            # Parse config into typed object
            if server_type == McpServerType.STDIO:
                # Parse STDIO config from JSON dict or string
                if isinstance(raw_config, str):
                    config_dict = json.loads(raw_config)
                else:
                    config_dict = raw_config
                # Extract first server from mcpServers
                mcp_servers_dict = config_dict.get('mcpServers', {})
                if mcp_servers_dict:
                    server_config = next(iter(mcp_servers_dict.values()))
                    typed_config: StdioMcpConfig | SseMcpConfig = StdioMcpConfig(
                        command=server_config['command'],
                        args=server_config.get('args', []),
                        env=server_config.get('env', {}),
                    )
                else:
                    # Legacy format: config is the server config directly
                    typed_config = StdioMcpConfig(
                        command=config_dict['command'],
                        args=config_dict.get('args', []),
                        env=config_dict.get('env', {}),
                    )
            else:
                # SSE config - URL string
                typed_config = SseMcpConfig(url=raw_config)

            servers[server_id] = McpServerMetadata(
                server_id=server_id,
                name=name,
                type=server_type,
                config=typed_config,
            )

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.exception(
                'Failed to load MCP server config',
                extra={'server_dir': server_dir.name, 'error': str(e)},
            )

    return servers


def load_enabled_mcp_server_ids() -> list[str]:
    """Return the ids of MCP servers whose on-disk config marks them enabled."""
    enabled: list[str] = []

    if not MCP_SERVERS_PATH.exists():
        return enabled

    for server_dir in MCP_SERVERS_PATH.iterdir():
        config_file = server_dir / 'config.json'
        if not (server_dir.is_dir() and config_file.exists()):
            continue
        try:
            with config_file.open() as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if data.get('enabled', False):
            enabled.append(server_dir.name)

    return enabled


def save_mcp_server(
    name: str,
    server_type: McpServerType,
    config: StdioMcpConfig | SseMcpConfig,
) -> str:
    """Save MCP server configuration to filesystem.

    Args:
        name: User-friendly server name
        server_type: Type of MCP server (stdio or sse)
        config: Server configuration (typed config object)

    Returns:
        server_id: The generated server ID

    """
    # Generate server_id: {slug}_{short_uuid}. The slug keeps the id (and thus
    # the on-disk directory name) filesystem-safe regardless of the user input.
    short_uuid = uuid.uuid4().hex[:8]
    server_id = f'{_slugify(name)}_{short_uuid}'

    server_dir = _resolve_server_dir(server_id)
    server_dir.mkdir(parents=True, exist_ok=True)
    # StdioMcpConfig.env may hold API keys/tokens, so keep the server directory
    # owner-only. Mirrors ubo_app/utils/secrets.py.
    server_dir.chmod(0o700)

    # Serialize typed config for filesystem storage
    if isinstance(config, StdioMcpConfig):
        # Store in mcpServers format for compatibility
        config_data: dict | str = {
            'mcpServers': {
                name: {
                    'command': config.command,
                    'args': config.args,
                    'env': config.env,
                },
            },
        }
    else:
        # SseMcpConfig - store URL directly
        config_data = config.url

    config_file = server_dir / 'config.json'
    data = {
        'name': name,
        'type': server_type.value,
        'config': config_data,
        'enabled': True,  # Default to enabled
    }

    # Create the file owner-only *before* writing the (possibly secret) config,
    # so there is no world-readable window. Opening in 'w' truncates but keeps
    # the existing mode. Mirrors ubo_app/utils/secrets.py.
    config_file.touch(mode=0o600, exist_ok=True)
    with config_file.open('w') as f:
        json.dump(data, f, indent=2)

    logger.info(
        'Saved MCP server configuration',
        extra={'server_id': server_id, 'server_name': name, 'type': server_type.value},
    )

    return server_id


def toggle_mcp_server(server_id: str) -> bool:
    """Toggle MCP server enabled state.

    Args:
        server_id: The server ID to toggle

    Returns:
        New enabled state (True if enabled, False if disabled)

    """
    server_dir = _resolve_server_dir(server_id)
    config_file = server_dir / 'config.json'

    if not config_file.exists():
        logger.warning(
            'Attempted to toggle non-existent MCP server',
            extra={'server_id': server_id},
        )
        return False

    try:
        with config_file.open() as f:
            data = json.load(f)

        # Toggle the enabled state (default to False if not present)
        current_state = data.get('enabled', False)
        new_state = not current_state
        data['enabled'] = new_state

        with config_file.open('w') as f:
            json.dump(data, f, indent=2)

        logger.info(
            'Toggled MCP server state',
            extra={'server_id': server_id, 'enabled': new_state},
        )
    except (json.JSONDecodeError, OSError) as e:
        logger.exception(
            'Failed to toggle MCP server state',
            extra={'server_id': server_id, 'error': str(e)},
        )
        return False
    else:
        return new_state


def delete_mcp_server(server_id: str) -> None:
    """Delete MCP server from filesystem.

    Args:
        server_id: The server ID to delete

    """
    server_dir = _resolve_server_dir(server_id)

    if not server_dir.exists():
        logger.warning(
            'Attempted to delete non-existent MCP server',
            extra={'server_id': server_id},
        )
        return

    shutil.rmtree(server_dir)
    logger.info('Deleted MCP server', extra={'server_id': server_id})


def validate_stdio_config(config_str: str) -> tuple[bool, str, dict | None]:
    """Validate stdio MCP server configuration JSON.

    Args:
        config_str: JSON string to validate

    Returns:
        Tuple of (is_valid, error_message, parsed_config)

    """
    try:
        config = json.loads(config_str)
    except json.JSONDecodeError as e:
        return False, f'Invalid JSON: {e}', None

    # Check for mcpServers key
    if 'mcpServers' not in config:
        return False, 'Missing "mcpServers" key in configuration', None

    mcp_servers = config['mcpServers']
    if not isinstance(mcp_servers, dict):
        return False, '"mcpServers" must be an object', None

    if not mcp_servers:
        return False, '"mcpServers" cannot be empty', None

    # Check that there's exactly one server
    if len(mcp_servers) != 1:
        return (
            False,
            'Configuration must contain exactly one server per form',
            None,
        )

    # Validate server structure
    server_name, server_config = next(iter(mcp_servers.items()))

    if not isinstance(server_config, dict):
        return False, f'Server "{server_name}" configuration must be an object', None

    # Check required fields for stdio
    if 'command' not in server_config:
        return False, f'Server "{server_name}" missing required "command" field', None

    return True, '', config


def validate_sse_url(url: str) -> tuple[bool, str]:
    """Validate SSE URL format.

    Args:
        url: URL string to validate

    Returns:
        Tuple of (is_valid, error_message)

    """
    if not url or not url.strip():
        return False, 'URL cannot be empty'

    url = url.strip()

    # Basic URL validation
    if not url.startswith(('http://', 'https://')):
        return False, 'URL must start with http:// or https://'

    # Check for basic URL structure
    if len(url) < 10:  # noqa: PLR2004
        return False, 'URL appears to be too short'

    return True, ''


def get_server_directories() -> Sequence[Path]:
    """Get all MCP server directories.

    Returns:
        List of Path objects for server directories

    """
    if not MCP_SERVERS_PATH.exists():
        return []

    return [
        d for d in MCP_SERVERS_PATH.iterdir() if d.is_dir()
    ]
