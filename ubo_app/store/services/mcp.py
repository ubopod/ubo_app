"""Definitions for MCP (Model Context Protocol) actions, events and state.

The MCP domain owns the configuration of MCP servers (add/enable/disable/sync)
and the aggregated state that the in-tree MCP gateway subprocess consumes over
gRPC. It used to live under the ``assistant`` slice; it now stands on its own so
the gateway can expose every configured server to any consumer (Pipecat, Claude
Desktop, hermes, OpenCLAW) instead of being reachable only from the assistant.
"""

from __future__ import annotations

import json
from dataclasses import field
from enum import StrEnum

from immutable import Immutable
from redux import BaseAction, BaseEvent

from ubo_app.utils.persistent_store import read_from_persistent_store


class McpServerType(StrEnum):
    """MCP server types."""

    STDIO = 'stdio'
    SSE = 'sse'


class StdioMcpConfig(Immutable):
    """Configuration for stdio MCP servers."""

    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


class SseMcpConfig(Immutable):
    """Configuration for SSE MCP servers."""

    url: str


class McpServerMetadata(Immutable):
    """Metadata for an MCP server."""

    server_id: str  # Format: {name}_{uuid}
    name: str  # User-friendly name
    type: McpServerType  # Server type enum
    config: StdioMcpConfig | SseMcpConfig  # Typed config - protobuf oneof


class EnabledMcpServersWithMetadata(Immutable):
    """Wrapper for list of enabled MCP servers with metadata.

    This wrapper is needed because gRPC selectors don't support
    container types (lists) directly.
    """

    items: list[McpServerMetadata] = field(default_factory=list)


class McpAction(BaseAction):
    """Base class for MCP actions."""


class McpAddServerAction(McpAction):
    """Action to add a new MCP server."""

    name: str
    type: McpServerType
    config: StdioMcpConfig | SseMcpConfig  # Typed config - protobuf oneof


class McpToggleServerAction(McpAction):
    """Action to enable/disable an MCP server."""

    server_id: str


class McpDeleteServerAction(McpAction):
    """Action to delete an MCP server."""

    server_id: str


class McpSyncServersAction(McpAction):
    """Action to sync MCP servers from filesystem."""


class McpSetServersAction(McpAction):
    """Action carrying MCP servers loaded from the filesystem.

    Dispatched by the MCP service's ``McpSyncServersEvent`` handler after it has
    read the on-disk configs, so the reducer can update the slice purely (no
    filesystem access inside the reduce cycle).
    """

    servers: list[McpServerMetadata]
    enabled_servers: list[str]


class McpEvent(BaseEvent):
    """Base class for MCP events."""


class McpAddServerEvent(McpEvent):
    """Event to add a new MCP server."""

    name: str
    type: McpServerType
    config: StdioMcpConfig | SseMcpConfig  # Typed config - protobuf oneof


class McpDeleteServerEvent(McpEvent):
    """Event to delete an MCP server."""

    server_id: str


class McpToggleServerEvent(McpEvent):
    """Event fired when an MCP server's enabled state is toggled.

    The reducer flips the in-memory ``enabled_mcp_servers`` purely; this event
    lets the MCP service persist the new state to the filesystem outside the
    reduce cycle.
    """

    server_id: str


class McpSyncServersEvent(McpEvent):
    """Event requesting a reload of MCP servers from the filesystem.

    Emitted by the reducer in response to ``McpSyncServersAction``; the MCP
    service reads the on-disk configs and dispatches ``McpSetServersAction``
    with the result.
    """


class McpState(Immutable):
    """State for the MCP service."""

    mcp_servers: dict[str, McpServerMetadata] = field(default_factory=dict)
    enabled_mcp_servers: list[str] = field(
        default_factory=lambda: read_from_persistent_store(
            'mcp:enabled_mcp_servers',
            default=[],
            mapper=lambda value: json.loads(value)
            if isinstance(value, str)
            else list(value),
        ),
    )
    # Enabled servers with full metadata for gRPC autorun (wrapped for gRPC)
    enabled_mcp_servers_with_metadata: EnabledMcpServersWithMetadata = field(
        default_factory=EnabledMcpServersWithMetadata,
    )
