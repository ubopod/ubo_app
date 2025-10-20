"""MCP server storage and management utilities."""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from typing import TYPE_CHECKING

from ubo_app.constants.assistant import ASSISTANT_MCP_SERVERS_PATH
from ubo_app.store.services.assistant import McpServerMetadata, McpServerType

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

logger = logging.getLogger(__name__)


def load_mcp_servers() -> dict[str, McpServerMetadata]:
    """Load all MCP servers from filesystem.

    Returns:
        Dictionary mapping server_id to McpServerMetadata

    """
    servers: dict[str, McpServerMetadata] = {}

    if not ASSISTANT_MCP_SERVERS_PATH.exists():
        ASSISTANT_MCP_SERVERS_PATH.mkdir(parents=True, exist_ok=True)
        return servers

    for server_dir in ASSISTANT_MCP_SERVERS_PATH.iterdir():
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
            config = data['config']

            # Extract server name from directory name (format: {name}_{uuid})
            server_id = server_dir.name
            name_parts = server_id.rsplit('_', 1)
            name = name_parts[0] if len(name_parts) == 2 else server_id  # noqa: PLR2004

            servers[server_id] = McpServerMetadata(
                server_id=server_id,
                name=name,
                type=server_type,
                config=config,
            )

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.exception(
                'Failed to load MCP server config',
                extra={'server_dir': server_dir.name, 'error': str(e)},
            )

    return servers


def save_mcp_server(
    name: str,
    server_type: McpServerType,
    config: str,
) -> str:
    """Save MCP server configuration to filesystem.

    Args:
        name: User-friendly server name
        server_type: Type of MCP server (stdio or sse)
        config: Server configuration (JSON string for stdio, URL string for sse)

    Returns:
        server_id: The generated server ID

    """
    # Generate server_id: {name}_{short_uuid}
    short_uuid = uuid.uuid4().hex[:8]
    server_id = f'{name}_{short_uuid}'

    server_dir = ASSISTANT_MCP_SERVERS_PATH / server_id
    server_dir.mkdir(parents=True, exist_ok=True)

    config_file = server_dir / 'config.json'
    data = {
        'type': server_type.value,
        'config': config,
        'enabled': True,  # Default to enabled
    }

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
    server_dir = ASSISTANT_MCP_SERVERS_PATH / server_id
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
    server_dir = ASSISTANT_MCP_SERVERS_PATH / server_id

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
    if not ASSISTANT_MCP_SERVERS_PATH.exists():
        return []

    return [
        d for d in ASSISTANT_MCP_SERVERS_PATH.iterdir() if d.is_dir()
    ]
