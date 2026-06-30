"""Translate the ubo MCP state into a FastMCP aggregating proxy.

The gateway subscribes to ``state.mcp.enabled_mcp_servers_with_metadata`` over
gRPC and turns it into a FastMCP ``mcpServers`` config. Each enabled server
becomes a backend of a single ``FastMCP`` proxy, whose aggregate tools are
exposed over both Streamable HTTP and SSE by :mod:`ubo_mcp_gateway.server`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Sequence


def _server_to_config_entry(metadata: Any) -> dict[str, Any] | None:  # noqa: ANN401
    """Translate one server's betterproto config into an MCPConfig entry.

    Mirrors the unwrap logic the assistant used in ``switch.py`` /
    ``tools.py``: the betterproto oneof exposes ``stdio_mcp_config`` /
    ``sse_mcp_config``, with ``args``/``env`` wrapped one level deeper.
    """
    config = getattr(metadata, 'config', None)
    if config is None:
        return None

    stdio_cfg = getattr(config, 'stdio_mcp_config', None)
    sse_cfg = getattr(config, 'sse_mcp_config', None)

    if stdio_cfg and getattr(stdio_cfg, 'command', None):
        args_wrapper = getattr(stdio_cfg, 'args', None)
        args = (
            list(args_wrapper.items)
            if args_wrapper and hasattr(args_wrapper, 'items')
            else []
        )
        env_wrapper = getattr(stdio_cfg, 'env', None)
        env = (
            dict(env_wrapper.items)
            if env_wrapper and hasattr(env_wrapper, 'items')
            else {}
        )
        return {'command': stdio_cfg.command, 'args': args, 'env': env}

    if sse_cfg and getattr(sse_cfg, 'url', None):
        return {'url': sse_cfg.url, 'transport': 'sse'}

    return None


def build_mcp_config(items: Sequence[Any]) -> dict[str, Any]:
    """Build a FastMCP ``{"mcpServers": {...}}`` config from autorun items.

    Args:
        items: The ``items`` list of the
            ``enabled_mcp_servers_with_metadata`` selector result.

    Returns:
        A FastMCP MCPConfig dict (possibly with an empty ``mcpServers``).

    """
    servers: dict[str, Any] = {}
    for metadata in items:
        server_id = getattr(metadata, 'server_id', None)
        if not server_id:
            continue
        entry = _server_to_config_entry(metadata)
        if entry is None:
            logger.warning(
                'Skipping MCP server with unknown config {extra}',
                extra={'server_id': server_id},
            )
            continue
        servers[server_id] = entry

    logger.info(
        'Built MCP gateway config {extra}',
        extra={'count': len(servers)},
    )
    return {'mcpServers': servers}


def extract_items(data: list) -> list:
    """Pull the metadata list out of the autorun callback payload.

    The selector is ``state.mcp.enabled_mcp_servers_with_metadata`` — an
    ``EnabledMcpServersWithMetadata`` wrapper whose ``items`` is itself a
    wrapper around the actual list (gRPC cannot carry bare lists).
    """
    if not data:
        return []
    wrapper = data[0]
    items_wrapper = getattr(wrapper, 'items', None)
    if items_wrapper is None:
        return []
    items = getattr(items_wrapper, 'items', [])
    return items if isinstance(items, list) else []
