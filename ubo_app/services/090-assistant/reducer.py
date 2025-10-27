# ruff: noqa: D100, D103
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from engines_registry import (
    IMAGE_GENERATOR_ENGINES,
    LLM_ENGINES,
    STT_ENGINES,
    TTS_ENGINES,
)
from redux import CompleteReducerResult, InitializationActionError
from redux.basic_types import InitAction

from ubo_app.logger import logger
from ubo_app.store.services.assistant import (
    AssistantAction,
    AssistantAddMcpServerAction,
    AssistantAddMcpServerEvent,
    AssistantDeleteMcpServerAction,
    AssistantDeleteMcpServerEvent,
    AssistantDownloadOllamaModelAction,
    AssistantDownloadOllamaModelEvent,
    AssistantEvent,
    AssistantHandleReportEvent,
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
    AssistantSyncMcpServersAction,
    AssistantToggleListeningAction,
    AssistantToggleMcpServerAction,
    AssistantUpdateProvidersAction,
)
from ubo_app.store.services.audio import (
    AudioAction,
    AudioDevice,
    AudioSetMuteStatusAction,
)
from ubo_app.store.services.notifications import (
    Chime,
    Importance,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.rgb_ring import RgbRingBlankAction, RgbRingRainbowAction

if TYPE_CHECKING:
    from redux import ReducerResult

    from ubo_app.store.services.notifications import NotificationsAction
    from ubo_app.store.services.rgb_ring import RgbRingAction

# MCP server_id format: name_uuid (2 parts when split by last underscore)
_MCP_SERVER_ID_PARTS = 2


def reducer(
    state: AssistantState | None,
    action: AssistantAction | AudioAction,
) -> ReducerResult[AssistantState, RgbRingAction | NotificationsAction, AssistantEvent]:
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

        case AssistantUpdateProvidersAction():
            all_engines = {
                **STT_ENGINES,
                **TTS_ENGINES,
                **LLM_ENGINES,
                **IMAGE_GENERATOR_ENGINES,
            }
            # Build setup status dict - this is the source of truth
            # Use getattr since not all engines have is_setup (only NeedsSetupMixin)
            provider_setup_status = {
                engine.name: getattr(engine, 'is_setup', True)
                for engine in all_engines.values()
            }
            return replace(
                state,
                provider_setup_status=provider_setup_status,
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

        case AudioSetMuteStatusAction(device=AudioDevice.INPUT):
            return replace(state, is_microphone_mute=action.is_mute)

        case AssistantStartListeningAction():
            if state.is_microphone_mute:
                return CompleteReducerResult(
                    state=state,
                    actions=[
                        NotificationsAddAction(
                            notification=Notification(
                                title='Microphone Muted',
                                content='Microphone is mute. Unmute to speak.',
                                importance=Importance.HIGH,
                                icon='󰍭',
                                display_type=NotificationDisplayType.STICKY,
                                chime=Chime.FAILURE,
                            ),
                        ),
                    ],
                )
            return CompleteReducerResult(
                state=state(is_listening=True),
                actions=[RgbRingRainbowAction(rounds=0, wait=800)],
            )

        case AssistantStopListeningAction():
            return CompleteReducerResult(
                state=state(is_listening=False),
                actions=[RgbRingBlankAction()],
            )

        case AssistantToggleListeningAction():
            if state.is_listening:
                # Currently listening, stop it
                return CompleteReducerResult(
                    state=state(is_listening=False),
                    actions=[RgbRingBlankAction()],
                )
            # Not listening, start it (with mute check)
            if state.is_microphone_mute:
                return CompleteReducerResult(
                    state=state,
                    actions=[
                        NotificationsAddAction(
                            notification=Notification(
                                title='Microphone Muted',
                                content='Microphone is mute. Unmute to speak.',
                                importance=Importance.HIGH,
                                icon='󰍭',
                                display_type=NotificationDisplayType.STICKY,
                                chime=Chime.FAILURE,
                            ),
                        ),
                    ],
                )
            return CompleteReducerResult(
                state=state(is_listening=True),
                actions=[RgbRingRainbowAction(rounds=0, wait=800)],
            )

        case AssistantAddMcpServerAction():
            logger.info(
                'AssistantAddMcpServerAction received',
                extra={'server_name': action.name, 'mcp_type': action.type.value},
            )
            return CompleteReducerResult(
                state=state,
                events=[
                    AssistantAddMcpServerEvent(
                        name=action.name,
                        type=action.type,
                        config=action.config,
                    ),
                ],
            )

        case AssistantToggleMcpServerAction():
            from mcp_servers import toggle_mcp_server

            # Toggle in filesystem
            new_state = toggle_mcp_server(action.server_id)
            logger.info(
                'AssistantToggleMCPServerAction processed',
                extra={'server_id': action.server_id, 'enabled': new_state},
            )

            # Update in-memory state
            enabled_servers = list(state.enabled_mcp_servers)
            if new_state:
                if action.server_id not in enabled_servers:
                    enabled_servers.append(action.server_id)
            elif action.server_id in enabled_servers:
                    enabled_servers.remove(action.server_id)

            # Serialize enabled servers with metadata for gRPC autorun
            import json

            enabled_with_metadata = [
                {
                    'server_id': state.mcp_servers[sid].server_id,
                    'name': state.mcp_servers[sid].name,
                    'type': state.mcp_servers[sid].type.value,  # Convert enum to string
                    'config': state.mcp_servers[sid].config,
                }
                for sid in enabled_servers
                if sid in state.mcp_servers
            ]
            enabled_mcp_servers_with_metadata_json = json.dumps(enabled_with_metadata)

            return replace(
                state,
                enabled_mcp_servers=enabled_servers,
                enabled_mcp_servers_with_metadata_json=enabled_mcp_servers_with_metadata_json,
            )

        case AssistantDeleteMcpServerAction():
            # Remove from enabled servers if present
            enabled_servers = list(state.enabled_mcp_servers)
            if action.server_id in enabled_servers:
                enabled_servers.remove(action.server_id)
            # Remove from mcp_servers dict
            mcp_servers = {
                k: v for k, v in state.mcp_servers.items() if k != action.server_id
            }
            # Serialize enabled servers with metadata for gRPC autorun
            import json

            enabled_with_metadata = [
                {
                    'server_id': mcp_servers[sid].server_id,
                    'name': mcp_servers[sid].name,
                    'type': mcp_servers[sid].type.value,  # Convert enum to string
                    'config': mcp_servers[sid].config,
                }
                for sid in enabled_servers
                if sid in mcp_servers
            ]
            enabled_mcp_servers_with_metadata_json = json.dumps(enabled_with_metadata)

            logger.info(
                'AssistantDeleteMCPServerAction processed',
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
                    enabled_mcp_servers_with_metadata_json=enabled_mcp_servers_with_metadata_json,
                ),
                events=[AssistantDeleteMcpServerEvent(server_id=action.server_id)],
            )

        case AssistantSyncMcpServersAction():
            # Load servers from filesystem and update state
            import json

            from ubo_app.constants.assistant import ASSISTANT_MCP_SERVERS_PATH
            from ubo_app.store.services.assistant import (
                McpServerMetadata,
                McpServerType,
            )

            loaded_servers: dict[str, McpServerMetadata] = {}
            enabled_servers: list[str] = []

            logger.debug(
                'Syncing MCP servers from filesystem',
                extra={'path': str(ASSISTANT_MCP_SERVERS_PATH),
                        'exists': ASSISTANT_MCP_SERVERS_PATH.exists(),
                    },
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
                        name = (
                            name_parts[0]
                            if len(name_parts) == _MCP_SERVER_ID_PARTS
                            else server_id
                        )

                        # Ensure config is always a string
                        # (JSON for dicts, plain string for URLs)
                        config = data['config']
                        if isinstance(config, dict):
                            config = json.dumps(config)

                        loaded_servers[server_id] = McpServerMetadata(
                            server_id=server_id,
                            name=name,
                            type=McpServerType(data['type']),  # Convert string to enum
                            config=config,
                        )

                        # Track enabled state from config file
                        if data.get('enabled', False):
                            enabled_servers.append(server_id)

                        logger.debug(
                            'Loaded MCP server',
                            extra={
                                'server_id': server_id,
                                'server_name': name,
                                'enabled': data.get('enabled', False),
                            },
                        )
                    except Exception:
                        logger.exception(
                            'Failed to load MCP server',
                            extra={'config_file': str(config_file)},
                        )
                        continue

            # Serialize enabled servers with metadata for gRPC autorun
            enabled_with_metadata = [
                {
                    'server_id': loaded_servers[sid].server_id,
                    'name': loaded_servers[sid].name,
                    'type': loaded_servers[sid].type.value,  # Convert enum to string
                    'config': loaded_servers[sid].config,
                }
                for sid in enabled_servers
                if sid in loaded_servers
            ]
            enabled_mcp_servers_with_metadata_json = json.dumps(enabled_with_metadata)

            logger.debug(
                'Finished syncing MCP servers',
                extra={'server_count': len(loaded_servers),
                    'server_ids': list(loaded_servers.keys()),
                    'enabled_count': len(enabled_servers),
                    },
            )

            return replace(
                state,
                mcp_servers=loaded_servers,
                enabled_mcp_servers=enabled_servers,
                enabled_mcp_servers_with_metadata_json=enabled_mcp_servers_with_metadata_json,
            )

        case _:
            return state
