"""Request handler — runs parametrized pipelines for ``AssistantRunPipelineEvent``.

Subscribes once to ``AssistantRunPipelineEvent`` and, per event, builds a short-lived
isolated pipeline for the requested contiguous STT/LLM/TTS sub-chain via
``pipeline_builder.build_request_pipeline`` and reports its output back over gRPC
through a ``GRPCTerminalCollector``.

Note: request-pipeline tool-calling (``enable_tools``) is not yet wired — the live
``draw_image``/``get_image`` tools need the live transports and MCP registration for
request pipelines is a follow-up. The context aggregator is still placed around the
LLM so the structural readiness is there.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.frames.frames import (
    EndFrame,
    Frame,
    InputAudioRawFrame,
    LLMRunFrame,
    LLMTextFrame,
    TextFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
)
from pipecat.processors.aggregators.llm_context import (
    LLMContext,
    LLMContextMessage,
)
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
)
from ubo_bindings.ubo.v1 import AssistantRunPipelineEvent, Event

from ubo_assistant.constants import DEFAULT_SYSTEM_MESSAGE
from ubo_assistant.grpc_collector import GRPCTerminalCollector
from ubo_assistant.pipeline_builder import (
    LLM,
    STT,
    TTS,
    build_request_pipeline,
    validate_stage_chain,
)
from ubo_assistant.request_providers import (
    build_llm_service,
    build_stt_service,
    build_tts_service,
)

if TYPE_CHECKING:
    from pipecat.processors.frame_processor import FrameProcessor
    from ubo_bindings.client import UboRPCClient

_MAX_CONCURRENT_REQUESTS = 3
_PIPELINE_IDLE_TIMEOUT_SECS = 120.0
_STT_FLUSH_TIMEOUT_SECS = 15.0
_TRAILING_SILENCE_SECONDS = 1.5
_AUDIO_CHUNK_SIZE = 640  # bytes — 20 ms of 16 kHz mono int16 audio
_PCM_SAMPLE_WIDTH = 2

# Map a betterproto enum *member name* to the provider id used by the factory. Names
# mostly match the lowercased value, except the Google/Generic LLMs whose member names
# (``GOOGLE``/``GENERIC``) differ from their provider ids.
_STAGE_IDS = {'STT': STT, 'LLM': LLM, 'TTS': TTS}
_STT_PROVIDER_IDS = {
    'VOSK': 'vosk',
    'GOOGLE_SEGMENTED': 'google_segmented',
    'GOOGLE': 'google',
    'OPENAI': 'openai',
    'DEEPGRAM': 'deepgram',
    'ASSEMBLYAI': 'assemblyai',
    'VENICE': 'venice',
}
_LLM_PROVIDER_IDS = {
    'OLLAMA': 'ollama',
    'OLLAMA_ONPREM': 'ollama_onprem',
    'GOOGLE': 'google_vertex',
    'OPENAI': 'openai',
    'GROK': 'grok',
    'CEREBRAS': 'cerebras',
    'ANTHROPIC': 'anthropic',
    'QWEN': 'qwen',
    'DEEPSEEK': 'deepseek',
    'OPENROUTER': 'openrouter',
    'MISTRAL': 'mistral',
    'VENICE': 'venice',
    'GENERIC': 'generic_llm',
}
_TTS_PROVIDER_IDS = {
    'PIPER': 'piper',
    'KOKORO': 'kokoro',
    'GOOGLE': 'google',
    'OPENAI': 'openai',
    'ELEVENLABS': 'elevenlabs',
    'RIME': 'rime',
    'VENICE': 'venice',
}
_IDLE_TIMEOUT_FRAMES: dict[str, tuple[type[Frame], ...]] = {
    STT: (TranscriptionFrame,),
    LLM: (LLMTextFrame,),
    TTS: (TTSAudioRawFrame,),
}


def setup_request_handler(client: UboRPCClient) -> None:
    """Subscribe to ``AssistantRunPipelineEvent`` and handle parametrized requests."""
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_REQUESTS)

    def _on_event(event: Event) -> None:
        run_event = event.assistant_run_pipeline_event
        if not run_event:
            return

        async def _guarded() -> None:
            async with semaphore:
                await _run_request(client, run_event)

        client.event_loop.create_task(_guarded())

    client.subscribe_event(
        event_type=Event(assistant_run_pipeline_event=AssistantRunPipelineEvent()),
        callback=_on_event,
    )
    logger.info('Assistant request handler registered')


async def _resolve_stage_services(
    stages: list[str],
    event: AssistantRunPipelineEvent,
    client: UboRPCClient,
) -> tuple[dict[str, FrameProcessor], str | None]:
    """Build the provider service for each requested stage.

    Returns ``(stage_services, error)`` — ``error`` is a message when a provider is
    unavailable, in which case ``stage_services`` is incomplete.
    """
    services: dict[str, FrameProcessor] = {}

    if STT in stages:
        provider_id = _STT_PROVIDER_IDS.get(event.stt_provider.name or '')
        if provider_id is None:
            return services, f'Unknown STT provider: {event.stt_provider.name}'
        service = await build_stt_service(provider_id, client=client)
        if service is None:
            return services, f"STT provider '{provider_id}' is not available"
        services[STT] = service

    if LLM in stages:
        provider_id = _LLM_PROVIDER_IDS.get(event.llm_provider.name or '')
        if provider_id is None:
            return services, f'Unknown LLM provider: {event.llm_provider.name}'
        service = await build_llm_service(
            provider_id,
            model=event.llm_model,
            client=client,
        )
        if service is None:
            return services, f"LLM provider '{provider_id}' is not available"
        services[LLM] = service

    if TTS in stages:
        provider_id = _TTS_PROVIDER_IDS.get(event.tts_provider.name or '')
        if provider_id is None:
            return services, f'Unknown TTS provider: {event.tts_provider.name}'
        service = await build_tts_service(provider_id, client=client)
        if service is None:
            return services, f"TTS provider '{provider_id}' is not available"
        services[TTS] = service

    return services, None


def _build_input_frames(
    stages: list[str],
    event: AssistantRunPipelineEvent,
) -> list[Frame]:
    """Build the frames to queue onto the request pipeline for its first stage."""
    if stages[0] == STT:
        sample_rate = event.sample_rate or 16000
        num_channels = event.num_channels or 1
        audio = event.audio
        frames: list[Frame] = [
            InputAudioRawFrame(
                audio=audio[offset : offset + _AUDIO_CHUNK_SIZE],
                sample_rate=sample_rate,
                num_channels=num_channels,
            )
            for offset in range(0, len(audio), _AUDIO_CHUNK_SIZE)
        ]
        # Trailing silence so streaming STT services and Vosk reach an end-of-utterance
        # and emit their final transcription before the pipeline is ended.
        silence_chunk = b'\x00' * _AUDIO_CHUNK_SIZE
        silence_bytes = (
            int(sample_rate * _TRAILING_SILENCE_SECONDS)
            * _PCM_SAMPLE_WIDTH
            * num_channels
        )
        frames.extend(
            InputAudioRawFrame(
                audio=silence_chunk,
                sample_rate=sample_rate,
                num_channels=num_channels,
            )
            for _ in range(silence_bytes // _AUDIO_CHUNK_SIZE)
        )
        return frames

    if stages[0] == LLM:
        # The user message is seeded into the LLMContext; trigger a completion.
        return [LLMRunFrame()]

    # TTS-first chain.
    return [TextFrame(text=event.text)]


async def _run_request(
    client: UboRPCClient,
    event: AssistantRunPipelineEvent,
) -> None:
    """Build and run a single parametrized request pipeline."""
    session_id = event.session_id
    stages = [
        _STAGE_IDS[stage.name]
        for stage in event.stages
        if stage.name in _STAGE_IDS
    ]
    terminal_stage = stages[-1] if stages else STT
    collector = GRPCTerminalCollector(
        client=client,
        session_id=session_id,
        terminal_stage=terminal_stage,
    )

    try:
        validate_stage_chain(stages)
    except ValueError as exception:
        collector.dispatch_error(str(exception))
        return

    stage_services, error = await _resolve_stage_services(stages, event, client)
    if error is not None:
        collector.dispatch_error(error)
        return

    context_aggregator: LLMContextAggregatorPair | None = None
    if LLM in stages:
        system_prompt = event.system_prompt or DEFAULT_SYSTEM_MESSAGE
        messages: list[LLMContextMessage] = [
            {'role': 'system', 'content': system_prompt},
        ]
        if stages[0] == LLM:
            messages.append({'role': 'user', 'content': event.text})
        context_aggregator = LLMContextAggregatorPair(
            LLMContext(messages, ToolsSchema(standard_tools=[])),
        )

    task, runner = build_request_pipeline(
        stages=stages,
        stage_services=stage_services,
        collector=collector,
        context_aggregator=context_aggregator,
        audio_in_sample_rate=event.sample_rate or 16000,
        idle_timeout_secs=_PIPELINE_IDLE_TIMEOUT_SECS,
        idle_timeout_frames=_IDLE_TIMEOUT_FRAMES[terminal_stage],
    )

    run_task = asyncio.create_task(runner.run(task))
    try:
        await task.queue_frames(_build_input_frames(stages, event))
        if stages[0] == STT:
            try:
                await asyncio.wait_for(
                    collector.first_output.wait(),
                    timeout=_STT_FLUSH_TIMEOUT_SECS,
                )
            except TimeoutError:
                logger.warning(
                    'STT produced no output before flush timeout',
                    extra={'session_id': session_id},
                )
        await task.queue_frame(EndFrame())
        await run_task
    except Exception:
        logger.exception(
            'Error running request pipeline',
            extra={'session_id': session_id},
        )
        if not run_task.done():
            await task.cancel()
            await run_task
        collector.dispatch_error('Internal error while running the pipeline')
        return

    if collector.output_count == 0 and not collector.sent_last_frame:
        collector.dispatch_error('Pipeline produced no output (provider timeout)')
    else:
        collector.dispatch_last_frame()
