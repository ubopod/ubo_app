"""Constants for the MCP service."""

from ubo_app.constants import CONFIG_PATH, MCP_GATEWAY_TOKEN_SECRET_ID

# On-disk store for MCP server configurations. Each server lives in its own
# ``{name}_{uuid}/config.json`` directory. This used to live under the assistant
# (``assistant_mcp_servers``); the MCP domain now owns it. ``init_service``
# migrates the old directory on first boot.
MCP_SERVERS_PATH = CONFIG_PATH / 'mcp_servers'
LEGACY_MCP_SERVERS_PATH = CONFIG_PATH / 'assistant_mcp_servers'

__all__ = [
    'LEGACY_MCP_SERVERS_PATH',
    'MCP_GATEWAY_TOKEN_SECRET_ID',
    'MCP_SERVERS_PATH',
]
