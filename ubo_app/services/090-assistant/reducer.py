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
    DEFAULT_MODELS,
    AssistantAction,
    AssistantAddGenericLLMProviderAction,
    AssistantAddMcpServerAction,
    AssistantAddMcpServerEvent,
    AssistantCompleteAction,
    AssistantDeleteMcpServerAction,
    AssistantDeleteMcpServerEvent,
    AssistantDownloadKokoroAction,
    AssistantDownloadKokoroEvent,
    AssistantDownloadOllamaModelAction,
    AssistantDownloadOllamaModelEvent,
    AssistantDownloadPiperVoiceAction,
    AssistantDownloadPiperVoiceEvent,
    AssistantDownloadVoskModelAction,
    AssistantDownloadVoskModelEvent,
    AssistantEvent,
    AssistantGenericLLMProviderChangedEvent,
    AssistantGenericLLMProviderRemovedEvent,
    AssistantHandleReportEvent,
    AssistantLLMName,
    AssistantModelChangedEvent,
    AssistantOllamaThinkingChangedEvent,
    AssistantPipelineStage,
    AssistantRemoveGenericLLMProviderAction,
    AssistantReportAction,
    AssistantRunPipelineAction,
    AssistantRunPipelineEvent,
    AssistantSelectGenericLLMProviderAction,
    AssistantSetIsActiveAction,
    AssistantSetKokoroDownloadedAction,
    AssistantSetMcpServersAction,
    AssistantSetOllamaDownloadedModelsAction,
    AssistantSetOllamaModelCapabilitiesAction,
    AssistantSetOllamaThinkingAction,
    AssistantSetPiperDownloadedVoicesAction,
    AssistantSetSelectedImageGeneratorAction,
    AssistantSetSelectedKokoroVoiceAction,
    AssistantSetSelectedLLMAction,
    AssistantSetSelectedModelAction,
    AssistantSetSelectedPiperVoiceAction,
    AssistantSetSelectedSTTAction,
    AssistantSetSelectedTTSAction,
    AssistantSetSelectedVoskModelAction,
    AssistantSetVoskDownloadedModelsAction,
    AssistantStartListeningAction,
    AssistantState,
    AssistantStopListeningAction,
    AssistantStopTalkingAction,
    AssistantStopTalkingEvent,
    AssistantSTTName,
    AssistantSyncMcpServersAction,
    AssistantSyncMcpServersEvent,
    AssistantSynthesizeAction,
    AssistantToggleListeningAction,
    AssistantToggleMcpServerAction,
    AssistantToggleMcpServerEvent,
    AssistantTranscribeAction,
    AssistantTTSName,
    AssistantUpdateProvidersAction,
    EnabledMcpServersWithMetadata,
    GenericLLMProvider,
    StopTalkingPhraseStopReason,
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


def _make_run_pipeline_event(  # noqa: PLR0913
    state: AssistantState,
    *,
    session_id: str,
    stages: list[AssistantPipelineStage],
    audio: bytes = b'',
    text: str = '',
    sample_rate: int = 16000,
    num_channels: int = 1,
    stt_provider: AssistantSTTName | None = None,
    llm_provider: AssistantLLMName | None = None,
    tts_provider: AssistantTTSName | None = None,
    llm_model: str | None = None,
    system_prompt: str | None = None,
    enable_tools: bool = False,
) -> AssistantRunPipelineEvent:
    """Build the canonical run-pipeline event, resolving providers/model from state."""
    resolved_llm = llm_provider if llm_provider is not None else state.selected_llm
    return AssistantRunPipelineEvent(
        session_id=session_id,
        stages=stages,
        audio=audio,
        text=text,
        sample_rate=sample_rate,
        num_channels=num_channels,
        stt_provider=stt_provider if stt_provider is not None else state.selected_stt,
        llm_provider=resolved_llm,
        tts_provider=tts_provider if tts_provider is not None else state.selected_tts,
        llm_model=llm_model
        if llm_model is not None
        else state.selected_models.get(resolved_llm, DEFAULT_MODELS[resolved_llm]),
        system_prompt=system_prompt,
        enable_tools=enable_tools,
        # Resolve per-engine selections so the request handler doesn't fall
        # back to hardcoded module defaults (live and one-shot pipelines must
        # agree on the same Vosk model / Piper voice / Kokoro voice).
        vosk_model_id=state.selected_vosk_model,
        piper_voice_id=state.selected_piper_voice,
        kokoro_voice_id=state.selected_kokoro_voice,
    )


def reducer(
    state: AssistantState | None,
    action: AssistantAction | AudioAction,
) -> ReducerResult[
    AssistantState,
    RgbRingAction | NotificationsAction | AudioAction | AssistantAction,
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

        case AssistantSetSelectedKokoroVoiceAction():
            # Plain state update — the assistant subprocess tracks
            # ``selected_kokoro_voice`` via a gRPC autorun and
            # ``KokoroTTSService`` rewrites its settings before the next
            # utterance, so no event is needed.
            return replace(state, selected_kokoro_voice=action.voice_id)

        case AssistantDownloadKokoroAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    AssistantDownloadKokoroEvent(voice_id=action.voice_id),
                ],
            )

        case AssistantSetKokoroDownloadedAction():
            return replace(state, kokoro_is_downloaded=action.downloaded)

        case AssistantSetSelectedVoskModelAction():
            # Plain state update — the assistant subprocess tracks
            # ``selected_vosk_model`` via a gRPC autorun and the
            # speech-recognition VoskEngine reloads the model on the next
            # recognizer reset, so no event is needed here.
            return replace(state, selected_vosk_model=action.model_id)

        case AssistantDownloadVoskModelAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    AssistantDownloadVoskModelEvent(model_id=action.model_id),
                ],
            )

        case AssistantSetVoskDownloadedModelsAction():
            return replace(
                state,
                vosk_downloaded_models=tuple(action.models),
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

        case AssistantAddGenericLLMProviderAction():
            # Upsert by id so re-running a registration (e.g. re-preparing the
            # Hermes composition) replaces the entry instead of duplicating it.
            providers = (
                *(
                    provider
                    for provider in state.generic_llm_providers
                    if provider.provider_id != action.provider_id
                ),
                GenericLLMProvider(
                    provider_id=action.provider_id,
                    label=action.label,
                ),
            )
            return replace(state, generic_llm_providers=providers)

        case AssistantRemoveGenericLLMProviderAction():
            was_selected = state.selected_generic_llm_provider == action.provider_id
            new_state = replace(
                state,
                generic_llm_providers=tuple(
                    provider
                    for provider in state.generic_llm_providers
                    if provider.provider_id != action.provider_id
                ),
            )
            if was_selected:
                new_state = replace(new_state, selected_generic_llm_provider='')
                if state.selected_llm == AssistantLLMName.GENERIC:
                    new_state = replace(
                        new_state,
                        selected_llm=AssistantLLMName.OLLAMA,
                    )
            return CompleteReducerResult(
                state=new_state,
                events=[
                    AssistantGenericLLMProviderRemovedEvent(
                        provider_id=action.provider_id,
                        was_selected=was_selected,
                    ),
                ],
            )

        case AssistantSelectGenericLLMProviderAction():
            # The event is emitted even when the same provider is re-selected:
            # the subprocess must re-read the canonical secrets after
            # credential edits, and its ``selected_llm`` autorun won't refire
            # while the value stays ``generic_llm``.
            return CompleteReducerResult(
                state=replace(
                    state,
                    selected_generic_llm_provider=action.provider_id,
                ),
                events=[
                    AssistantGenericLLMProviderChangedEvent(
                        provider_id=action.provider_id,
                    ),
                ],
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
                    active_audio_source=action.audio_source,
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
                    active_audio_source='',
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
                    # The user wants to fully exit the interaction — silence
                    # the bot AND end any active listening session, so any
                    # subsequent words don't get captured as a follow-up turn.
                    AssistantStopListeningAction(
                        reason=StopTalkingPhraseStopReason(),
                    ),
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
                        active_audio_source='',
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
                    active_audio_source=action.audio_source,
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
            # Flip the in-memory enabled state purely; the on-disk write is
            # performed by the AssistantToggleMcpServerEvent handler in setup.py.
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
                events=[AssistantToggleMcpServerEvent(server_id=action.server_id)],
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
            # The filesystem read is done by the AssistantSyncMcpServersEvent
            # handler in setup.py, which dispatches AssistantSetMcpServersAction
            # with the result — keeping this reducer pure.
            return CompleteReducerResult(
                state=state,
                events=[AssistantSyncMcpServersEvent()],
            )

        case AssistantSetMcpServersAction():
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

        case AssistantTranscribeAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    _make_run_pipeline_event(
                        state,
                        session_id=action.session_id,
                        stages=[AssistantPipelineStage.STT],
                        audio=action.audio,
                        sample_rate=action.sample_rate,
                        num_channels=action.num_channels,
                        stt_provider=action.stt_provider,
                    ),
                ],
            )

        case AssistantSynthesizeAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    _make_run_pipeline_event(
                        state,
                        session_id=action.session_id,
                        stages=[AssistantPipelineStage.TTS],
                        text=action.text,
                        tts_provider=action.tts_provider,
                    ),
                ],
            )

        case AssistantCompleteAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    _make_run_pipeline_event(
                        state,
                        session_id=action.session_id,
                        stages=[AssistantPipelineStage.LLM],
                        text=action.text,
                        llm_provider=action.llm_provider,
                        system_prompt=action.system_prompt,
                        enable_tools=action.enable_tools,
                    ),
                ],
            )

        case AssistantRunPipelineAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    _make_run_pipeline_event(
                        state,
                        session_id=action.session_id,
                        stages=action.stages,
                        audio=action.audio,
                        text=action.text,
                        sample_rate=action.sample_rate,
                        num_channels=action.num_channels,
                        stt_provider=action.stt_provider,
                        llm_provider=action.llm_provider,
                        tts_provider=action.tts_provider,
                        llm_model=action.llm_model,
                        system_prompt=action.system_prompt,
                        enable_tools=action.enable_tools,
                    ),
                ],
            )

        case _:
            return state
