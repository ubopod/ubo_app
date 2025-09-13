# ruff: noqa: D100, D103
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from redux import CompleteReducerResult, InitializationActionError
from redux.basic_types import InitAction

from ubo_app.constants.assistant import VOSK_MODEL_PATH
from ubo_app.logger import logger
from ubo_app.store.services.assistant import (
    AssistantAction,
    AssistantAddMCPServerAction,
    AssistantAddMCPServerEvent,
    AssistantDeleteMCPServerAction,
    AssistantDeleteMCPServerEvent,
    AssistantDownloadOllamaModelAction,
    AssistantDownloadOllamaModelEvent,
    AssistantEvent,
    AssistantHandleReportEvent,
    AssistantQueryMCPServersAction,
    AssistantQueryMCPServersEvent,
    AssistantReportAction,
    AssistantSetIsActiveAction,
    AssistantSetSelectedImageGeneratorAction,
    AssistantSetSelectedLLMAction,
    AssistantSetSelectedModelAction,
    AssistantSetSelectedSTTAction,
    AssistantSetSelectedTTSAction,
    AssistantStartListeningAction,
    AssistantState,
    AssistantStopListeningAction,
    AssistantSyncMCPServersAction,
    AssistantSyncMCPServersEvent,
    AssistantToggleMCPServerAction,
)
from ubo_app.store.services.rgb_ring import RgbRingBlankAction, RgbRingRainbowAction

if TYPE_CHECKING:
    from redux import ReducerResult

    from ubo_app.store.services.rgb_ring import RgbRingAction


def reducer(
    state: AssistantState | None,
    action: AssistantAction,
) -> ReducerResult[AssistantState, RgbRingAction, AssistantEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return AssistantState()

        raise InitializationActionError(action)

    match action:
        case AssistantSetIsActiveAction():
            return replace(state, is_active=action.is_active)

        case AssistantSetSelectedSTTAction():
            return replace(state, selected_stt=action.stt_name)

        case AssistantSetSelectedLLMAction():
            return replace(state, selected_llm=action.llm_name)

        case AssistantSetSelectedTTSAction():
            return replace(state, selected_tts=action.tts_name)

        case AssistantSetSelectedImageGeneratorAction():
            return replace(state, selected_image_generator=action.image_generator_name)

        case AssistantSetSelectedModelAction():
            return replace(
                state,
                selected_models={
                    **state.selected_models,
                    state.selected_llm: action.model,
                },
            )

        case AssistantDownloadOllamaModelAction():
            return CompleteReducerResult(
                state=state,
                events=[AssistantDownloadOllamaModelEvent(model=action.model)],
            )

        case AssistantReportAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    AssistantHandleReportEvent(
                        source_id=action.source_id,
                        data=action.data,
                    ),
                ],
            )

        case AssistantStartListeningAction():
            return CompleteReducerResult(
                state=state(is_listening=True),
                actions=[RgbRingRainbowAction(rounds=0, wait=800)],
            )

        case AssistantStopListeningAction():
            return CompleteReducerResult(
                state=state(is_listening=False),
                actions=[RgbRingBlankAction()],
            )

        case AssistantAddMCPServerAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    AssistantAddMCPServerEvent(
                        name=action.name,
                        type=action.type,
                        config=action.config,
                    ),
                ],
            )

        case AssistantToggleMCPServerAction():
            from mcp_servers import toggle_mcp_server

            # Toggle in filesystem
            new_state = toggle_mcp_server(action.server_id)

            # Update in-memory state
            enabled_servers = state.enabled_mcp_servers.copy()
            if new_state:
                enabled_servers.add(action.server_id)
            else:
                enabled_servers.discard(action.server_id)

            return replace(state, enabled_mcp_servers=enabled_servers)

        case AssistantDeleteMCPServerAction():
            # Remove from enabled servers if present
            enabled_servers = state.enabled_mcp_servers.copy()
            enabled_servers.discard(action.server_id)
            # Remove from mcp_servers dict
            mcp_servers = {
                k: v for k, v in state.mcp_servers.items() if k != action.server_id
            }
            return CompleteReducerResult(
                state=replace(
                    state,
                    enabled_mcp_servers=enabled_servers,
                    mcp_servers=mcp_servers,
                ),
                events=[AssistantDeleteMCPServerEvent(server_id=action.server_id)],
            )

        case AssistantSyncMCPServersAction():
            # Load servers from filesystem and update state
            import json

            from ubo_app.constants.assistant import ASSISTANT_MCP_SERVERS_PATH
            from ubo_app.store.services.assistant import (
                MCPServerMetadata,
                MCPServerType,
            )

            loaded_servers: dict[str, MCPServerMetadata] = {}

            logger.debug(
                'Syncing MCP servers from filesystem',
                extra={'path': str(ASSISTANT_MCP_SERVERS_PATH), 'exists': ASSISTANT_MCP_SERVERS_PATH.exists()},
            )

            if ASSISTANT_MCP_SERVERS_PATH.exists():
                # Iterate through server directories
                for server_dir in ASSISTANT_MCP_SERVERS_PATH.iterdir():
                    if not server_dir.is_dir():
                        continue

                    config_file = server_dir / 'config.json'
                    if not config_file.exists():
                        continue

                    try:
                        with config_file.open() as f:
                            data = json.load(f)

                        server_id = server_dir.name
                        # Extract name from server_id (format: name_uuid)
                        name_parts = server_id.rsplit('_', 1)
                        name = name_parts[0] if len(name_parts) == 2 else server_id

                        loaded_servers[server_id] = MCPServerMetadata(
                            server_id=server_id,
                            name=name,
                            type=MCPServerType(data['type']),
                            config=data['config'],
                        )
                        logger.debug(
                            'Loaded MCP server',
                            extra={'server_id': server_id, 'server_name': name},
                        )
                    except Exception:
                        logger.exception(
                            'Failed to load MCP server',
                            extra={'config_file': str(config_file)},
                        )
                        continue

            logger.debug(
                'Finished syncing MCP servers',
                extra={'server_count': len(loaded_servers), 'server_ids': list(loaded_servers.keys())},
            )

            return CompleteReducerResult(
                state=replace(state, mcp_servers=loaded_servers),
                events=[AssistantSyncMCPServersEvent()],
            )

        case AssistantQueryMCPServersAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    AssistantQueryMCPServersEvent(
                        mcp_servers=state.mcp_servers,
                        enabled_mcp_servers=state.enabled_mcp_servers,
                    ),
                ],
            )

        case _:
            return state
