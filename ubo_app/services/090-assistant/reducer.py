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
    AssistantDownloadPiperVoiceAction,
    AssistantDownloadPiperVoiceEvent,
    AssistantEvent,
    AssistantHandleReportEvent,
    AssistantModelChangedEvent,
    AssistantOllamaThinkingChangedEvent,
    AssistantReportAction,
    AssistantSetIsActiveAction,
    AssistantSetOllamaDownloadedModelsAction,
    AssistantSetOllamaModelCapabilitiesAction,
    AssistantSetOllamaThinkingAction,
    AssistantSetPiperDownloadedVoicesAction,
    AssistantSetSelectedImageGeneratorAction,
    AssistantSetSelectedLLMAction,
    AssistantSetSelectedModelAction,
    AssistantSetSelectedPiperVoiceAction,
    AssistantSetSelectedSTTAction,
    AssistantSetSelectedTTSAction,
    AssistantStartListeningAction,
    AssistantState,
    AssistantStopListeningAction,
    AssistantStopTalkingAction,
    AssistantStopTalkingEvent,
    AssistantSyncMcpServersAction,
    AssistantToggleListeningAction,
    AssistantToggleMcpServerAction,
    AssistantUpdateProvidersAction,
    UserStopReason,
    resolve_policy,
)
from ubo_app.store.services.audio import (
    AudioAction,
    AudioDevice,
    AudioSetMuteStatusAction,
    AudioStopPlaybackAction,
)
from ubo_app.store.services.notifications import (
    Chime,
    Importance,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.rgb_ring import (
    RgbRingBlankAction,
    RgbRingBlinkAction,
    RgbRingRainbowAction,
)

if TYPE_CHECKING:
    from redux import ReducerResult

    from ubo_app.store.services.notifications import NotificationsAction
    from ubo_app.store.services.rgb_ring import RgbRingAction

# MCP server_id format: name_uuid (2 parts when split by last underscore)
_MCP_SERVER_ID_PARTS = 2


def reducer(
    state: AssistantState | None,
    action: AssistantAction | AudioAction,
) -> ReducerResult[
    AssistantState,
    RgbRingAction | NotificationsAction | AudioAction,
    AssistantEvent,
]:
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
            llm_name = action.llm_name or state.selected_llm
            new_state = replace(
                state,
                selected_models={
                    **state.selected_models,
                    llm_name: action.model,
                },
            )
            return CompleteReducerResult(
                state=new_state,
                events=[
                    AssistantModelChangedEvent(
                        llm_name=llm_name,
                        model=action.model,
                    ),
                ],
            )

        case AssistantDownloadOllamaModelAction():
            return CompleteReducerResult(
                state=state,
                events=[AssistantDownloadOllamaModelEvent(model=action.model)],
            )

        case AssistantSetOllamaModelCapabilitiesAction():
            return replace(
                state,
                ollama_model_capabilities={
                    **state.ollama_model_capabilities,
                    action.model: tuple(action.capabilities),
                },
            )

        case AssistantSetOllamaDownloadedModelsAction():
            return replace(
                state,
                ollama_downloaded_models=tuple(action.models),
                ollama_downloaded_models_refreshed=True,
            )

        case AssistantSetOllamaThinkingAction():
            return CompleteReducerResult(
                state=replace(
                    state,
                    ollama_thinking_enabled={
                        **state.ollama_thinking_enabled,
                        action.model: action.enabled,
                    },
                ),
                events=[
                    AssistantOllamaThinkingChangedEvent(
                        model=action.model,
                        enabled=action.enabled,
                    ),
                ],
            )

        case AssistantSetSelectedPiperVoiceAction():
            # Plain state update — the assistant subprocess tracks
            # ``selected_piper_voice`` via a gRPC autorun, and
            # ``PiperTTSService.run_tts`` reconciles the loaded model with
            # the selection before each utterance, so no event is needed.
            return replace(state, selected_piper_voice=action.voice_id)

        case AssistantDownloadPiperVoiceAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    AssistantDownloadPiperVoiceEvent(voice_id=action.voice_id),
                ],
            )

        case AssistantSetPiperDownloadedVoicesAction():
            return replace(
                state,
                piper_downloaded_voices=tuple(action.voices),
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
            if action.source is None:
                logger.warning(
                    'AssistantStartListeningAction dispatched without a source; '
                    'no per-trigger policy will apply',
                )
            return CompleteReducerResult(
                state=state(
                    is_listening=True,
                    active_source=action.source,
                    active_policy=resolve_policy(state.policies, action.source),
                ),
                actions=[RgbRingRainbowAction(rounds=0, wait=800)],
            )

        case AssistantStopListeningAction():
            if action.reason is None:
                logger.warning(
                    'AssistantStopListeningAction dispatched without a reason',
                )
            return CompleteReducerResult(
                state=state(
                    is_listening=False,
                    active_source=None,
                    active_policy=None,
                    last_stop_reason=action.reason,
                ),
                actions=[RgbRingBlankAction()],
            )

        case AssistantStopTalkingAction():
            return CompleteReducerResult(
                state=state,
                actions=[
                    RgbRingBlinkAction(
                        color=(255, 0, 255),
                        repetitions=1,
                        wait=200,
                    ),
                    # Pipecat's InterruptionFrame stops the TTS service, but the
                    # core's audio_manager has a multi-second queue of already-
                    # dispatched AudioSample chunks. AudioStopPlaybackAction
                    # clears that queue and stops the current PCM stream so the
                    # speaker falls silent immediately.
                    AudioStopPlaybackAction(),
                ],
                events=[AssistantStopTalkingEvent()],
            )

        case AssistantToggleListeningAction():
            if state.is_listening:
                # Currently listening, stop it.
                stop_reason = (
                    UserStopReason(source=action.source)
                    if action.source is not None
                    else None
                )
                return CompleteReducerResult(
                    state=state(
                        is_listening=False,
                        active_source=None,
                        active_policy=None,
                        last_stop_reason=stop_reason,
                    ),
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
                state=state(
                    is_listening=True,
                    active_source=action.source,
                    active_policy=resolve_policy(state.policies, action.source),
                ),
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

            # Build enabled servers with metadata for gRPC autorun
            from ubo_app.store.services.assistant import EnabledMcpServersWithMetadata

            enabled_with_metadata = EnabledMcpServersWithMetadata(
                items=[
                    state.mcp_servers[sid]
                    for sid in enabled_servers
                    if sid in state.mcp_servers
                ],
            )

            return replace(
                state,
                enabled_mcp_servers=enabled_servers,
                enabled_mcp_servers_with_metadata=enabled_with_metadata,
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
            # Build enabled servers with metadata for gRPC autorun
            from ubo_app.store.services.assistant import EnabledMcpServersWithMetadata

            enabled_with_metadata = EnabledMcpServersWithMetadata(
                items=[
                    mcp_servers[sid]
                    for sid in enabled_servers
                    if sid in mcp_servers
                ],
            )

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
                    enabled_mcp_servers_with_metadata=enabled_with_metadata,
                ),
                events=[AssistantDeleteMcpServerEvent(server_id=action.server_id)],
            )

        case AssistantSyncMcpServersAction():
            # Load servers from filesystem and update state
            import json

            from ubo_app.constants.assistant import ASSISTANT_MCP_SERVERS_PATH
            from ubo_app.store.services.assistant import (
                EnabledMcpServersWithMetadata,
                McpServerMetadata,
                McpServerType,
                SseMcpConfig,
                StdioMcpConfig,
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

                        server_type = McpServerType(data['type'])
                        raw_config = data['config']

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
                                typed_config: StdioMcpConfig | SseMcpConfig = (
                                    StdioMcpConfig(
                                        command=server_config['command'],
                                        args=server_config.get('args', []),
                                        env=server_config.get('env', {}),
                                    )
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

                        loaded_servers[server_id] = McpServerMetadata(
                            server_id=server_id,
                            name=name,
                            type=server_type,
                            config=typed_config,
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

            # Build enabled servers with metadata for gRPC autorun
            enabled_with_metadata = EnabledMcpServersWithMetadata(
                items=[
                    loaded_servers[sid]
                    for sid in enabled_servers
                    if sid in loaded_servers
                ],
            )

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
                enabled_mcp_servers_with_metadata=enabled_with_metadata,
            )

        case _:
            return state
