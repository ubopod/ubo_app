# ruff: noqa: D100, D103
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from redux import CompleteReducerResult, InitializationActionError
from redux.basic_types import InitAction

from ubo_app.logger import logger
from ubo_app.store.services.mcp import (
    EnabledMcpServersWithMetadata,
    McpAction,
    McpAddServerAction,
    McpAddServerEvent,
    McpDeleteServerAction,
    McpDeleteServerEvent,
    McpEvent,
    McpSetServersAction,
    McpState,
    McpSyncServersAction,
    McpSyncServersEvent,
    McpToggleServerAction,
    McpToggleServerEvent,
)

if TYPE_CHECKING:
    from redux import ReducerResult


def reducer(
    state: McpState | None,
    action: McpAction,
) -> ReducerResult[McpState, McpAction, McpEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return McpState()

        raise InitializationActionError(action)

    match action:
        case McpAddServerAction():
            logger.info(
                'McpAddServerAction received',
                extra={'server_name': action.name, 'mcp_type': action.type.value},
            )
            return CompleteReducerResult(
                state=state,
                events=[
                    McpAddServerEvent(
                        name=action.name,
                        type=action.type,
                        config=action.config,
                    ),
                ],
            )

        case McpToggleServerAction():
            # Flip the in-memory enabled state purely; the on-disk write is
            # performed by the McpToggleServerEvent handler in setup.py.
            enabled_servers = list(state.enabled_mcp_servers)
            if action.server_id in enabled_servers:
                enabled_servers.remove(action.server_id)
            else:
                enabled_servers.append(action.server_id)

            enabled_with_metadata = EnabledMcpServersWithMetadata(
                items=[
                    state.mcp_servers[sid]
                    for sid in enabled_servers
                    if sid in state.mcp_servers
                ],
            )

            return CompleteReducerResult(
                state=replace(
                    state,
                    enabled_mcp_servers=enabled_servers,
                    enabled_mcp_servers_with_metadata=enabled_with_metadata,
                ),
                events=[McpToggleServerEvent(server_id=action.server_id)],
            )

        case McpDeleteServerAction():
            # Remove from enabled servers if present
            enabled_servers = list(state.enabled_mcp_servers)
            if action.server_id in enabled_servers:
                enabled_servers.remove(action.server_id)
            # Remove from mcp_servers dict
            mcp_servers = {
                k: v for k, v in state.mcp_servers.items() if k != action.server_id
            }
            # Build enabled servers with metadata for gRPC autorun
            enabled_with_metadata = EnabledMcpServersWithMetadata(
                items=[
                    mcp_servers[sid]
                    for sid in enabled_servers
                    if sid in mcp_servers
                ],
            )

            logger.info(
                'McpDeleteServerAction processed',
                extra={
                    'server_id': action.server_id,
                    'remaining_servers': len(mcp_servers),
                    'remaining_enabled': len(enabled_servers),
                },
            )
            return CompleteReducerResult(
                state=replace(
                    state,
                    enabled_mcp_servers=enabled_servers,
                    mcp_servers=mcp_servers,
                    enabled_mcp_servers_with_metadata=enabled_with_metadata,
                ),
                events=[McpDeleteServerEvent(server_id=action.server_id)],
            )

        case McpSyncServersAction():
            # The filesystem read is done by the McpSyncServersEvent handler in
            # setup.py, which dispatches McpSetServersAction with the result —
            # keeping this reducer pure.
            return CompleteReducerResult(
                state=state,
                events=[McpSyncServersEvent()],
            )

        case McpSetServersAction():
            mcp_servers = {server.server_id: server for server in action.servers}
            enabled_servers = [
                server_id
                for server_id in action.enabled_servers
                if server_id in mcp_servers
            ]
            enabled_with_metadata = EnabledMcpServersWithMetadata(
                items=[mcp_servers[sid] for sid in enabled_servers],
            )
            return replace(
                state,
                mcp_servers=mcp_servers,
                enabled_mcp_servers=enabled_servers,
                enabled_mcp_servers_with_metadata=enabled_with_metadata,
            )

        case _:
            return state
