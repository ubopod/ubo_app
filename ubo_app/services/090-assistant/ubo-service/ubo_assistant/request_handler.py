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
import contextlib
import os
from typing import TYPE_CHECKING

from loguru import logger
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.frames.frames import (
    EndFrame,
    ErrorFrame,
    Frame,
    InputAudioRawFrame,
    LLMRunFrame,
    LLMTextFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.aggregators.llm_context import (
    LLMContext,
    LLMContextMessage,
)
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
)
from pipecat.services.stt_service import SegmentedSTTService
from ubo_bindings.ubo.v1 import (
    AssistantCancelRequestEvent,
    AssistantPipelineStage,
    AssistantRunPipelineEvent,
    Event,
)

from ubo_assistant.error_notification import is_transient_error
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
from ubo_assistant.vosk import VoskSTTService

if TYPE_CHECKING:
    from pipecat.pipeline.task import PipelineTask
    from pipecat.processors.frame_processor import FrameProcessor
    from ubo_bindings.client import UboRPCClient

    from ubo_assistant.system_prompt_watcher import SystemPromptWatcher

_MAX_CONCURRENT_REQUESTS = 3
_PIPELINE_IDLE_TIMEOUT_SECS = 120.0
# Bound time-to-first-output, NOT total time. The pipeline's own idle-timeout
# does not always unblock ``await run_task`` (a websocket TTS service can leave
# the runner unable to finish), so without a cap a stuck request holds its
# concurrency slot forever and, after ``_MAX_CONCURRENT_REQUESTS`` such
# requests, wedges the whole handler. We cap how long we wait for the FIRST
# output frame — a provider the one-shot can't drive never produces one — and
# once output is flowing we let the read finish, so a slow/long but
# progressing provider (e.g. Venice) is never truncated mid-read.
_FIRST_OUTPUT_TIMEOUT_SECS = 45.0
# Generous backstop once output has started, guarding only the pathological
# "produced a frame then stalled forever" case; normal reads finish well within.
_RUN_TASK_BACKSTOP_SECS = 300.0
# Grace period to let a force-cancelled run task unwind before we give up on it.
_CANCEL_GRACE_SECS = 5.0
_STT_FLUSH_TIMEOUT_SECS = 15.0
# Fallback quiescence window for STT services without a deterministic finalize
# signal: after the first transcript, keep collecting while new output keeps
# arriving within this window, so an eager EndFrame/disconnect doesn't truncate a
# multi-segment transcript. (Deepgram/segmented services exit early via their
# finalized signal, so this only bounds the no-signal providers.)
_STT_QUIESCENCE_SECS = 3.0
# Silent lead-in fed (at real time) before the speech audio for cloud streaming
# STT. Their websocket connects asynchronously and ``run_stt`` drops audio sent
# before it's up; feeding silence first lets the connection establish during the
# silence — mirroring the ambient pre-speech gap a live mic always provides — so
# no speech is ever dropped. This replaces peeking at Deepgram's private
# ``_connection_ready`` event. Generous by default; tune via env if a slow
# network needs longer for the handshake.
_LEADING_SILENCE_SECONDS = 1.5
_TRAILING_SILENCE_SECONDS = 1.5
_AUDIO_CHUNK_SIZE = 640  # bytes — 20 ms of 16 kHz mono int16 audio
_PCM_SAMPLE_WIDTH = 2


def _env_float(name: str, default: float) -> float:
    """Read a float override from the environment, falling back on a bad value.

    These timeouts are parsed at the top of ``_run_request``, before the error
    path is set up. A malformed override (e.g. ``UBO_ASSISTANT_*=fast``) must not
    raise there — that would kill the request without ever dispatching an error
    frame, leaving the caller to hang. Parse defensively and keep the default.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning(
            'screen-reader: ignoring non-numeric {name}={raw!r}; using {default}',
            name=name,
            raw=raw,
            default=default,
        )
        return default


# Map a betterproto enum *member name* to the provider id used by the factory. Names
# mostly match the lowercased value, except the Google/Generic LLMs whose member names
# (``GOOGLE``/``GENERIC``) differ from their provider ids.
_STAGE_IDS = {'STT': STT, 'LLM': LLM, 'TTS': TTS}
_STT_PROVIDER_IDS = {
    'VOSK': 'vosk',
    'MOONSHINE': 'moonshine',
    'GOOGLE_SEGMENTED': 'google_segmented',
    'GOOGLE': 'google',
    'OPENAI': 'openai',
    'DEEPGRAM': 'deepgram',
    'ASSEMBLYAI': 'assemblyai',
    'VENICE': 'venice',
    'MISTRAL': 'mistral',
    'ELEVENLABS': 'elevenlabs',
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
    'DEEPGRAM': 'deepgram',
    'MISTRAL': 'mistral',
}
_IDLE_TIMEOUT_FRAMES: dict[str, tuple[type[Frame], ...]] = {
    STT: (TranscriptionFrame,),
    LLM: (LLMTextFrame,),
    TTS: (TTSAudioRawFrame,),
}


def setup_request_handler(
    client: UboRPCClient,
    system_prompt_watcher: SystemPromptWatcher,
) -> None:
    """Subscribe to ``AssistantRunPipelineEvent`` and handle parametrized requests."""
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_REQUESTS)
    requests: dict[str, asyncio.Task[None]] = {}

    def _on_event(event: Event) -> None:
        run_event = event.assistant_run_pipeline_event
        if not run_event:
            return

        async def _guarded() -> None:
            async with semaphore:
                await _run_request(client, run_event, system_prompt_watcher)

        request = client.event_loop.create_task(_guarded())
        requests[run_event.session_id] = request

        def _forget_request(_task: asyncio.Task[None]) -> None:
            requests.pop(run_event.session_id, None)

        request.add_done_callback(_forget_request)

    def _on_cancel(event: Event) -> None:
        cancel_event = event.assistant_cancel_request_event
        if cancel_event is None:
            return
        request = requests.pop(cancel_event.session_id, None)
        if request is not None:
            request.cancel()

    client.subscribe_event(
        event_type=Event(assistant_run_pipeline_event=AssistantRunPipelineEvent()),
        callback=_on_event,
    )
    client.subscribe_event(
        event_type=Event(assistant_cancel_request_event=AssistantCancelRequestEvent()),
        callback=_on_cancel,
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
        service = await build_stt_service(
            provider_id,
            client=client,
            vosk_model_id=event.vosk_model_id or '',
            moonshine_model_id=event.moonshine_model_id or '',
        )
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
        message = (
            f'screen-reader: resolving TTS provider '
            f'{event.tts_provider.name!r} -> provider_id={provider_id!r}'
        )
        logger.info(message)
        if provider_id is None:
            return services, f'Unknown TTS provider: {event.tts_provider.name}'
        service = await build_tts_service(
            provider_id,
            client=client,
            piper_voice_id=event.piper_voice_id or '',
            kokoro_voice_id=event.kokoro_voice_id or '',
            tts_voice_id=event.tts_voice_id or '',
        )
        if service is None:
            message = (
                f'screen-reader: build_tts_service returned None for '
                f'provider_id={provider_id!r} (credential missing/unresolved)'
            )
            logger.error(message)
            return services, f"TTS provider '{provider_id}' is not available"
        logger.info(f'screen-reader: TTS service built for {provider_id!r}')  # noqa: G004
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
        # Bracket the audio with VAD speaking frames. Without a VAD analyzer in
        # the one-shot pipeline these are never generated, so: segmented STT
        # services (Whisper-based: OpenAI, Venice) never get the stop event that
        # triggers transcription of the buffered segment — and discard all but
        # the last 1s of audio while "not speaking" — and Deepgram never sends
        # its Finalize (it does so on VADUserStoppedSpeakingFrame). InputAudioRaw
        # and VAD frames are both SystemFrames, so this ordering is preserved.
        frames: list[Frame] = [VADUserStartedSpeakingFrame()]
        frames.extend(
            InputAudioRawFrame(
                audio=audio[offset : offset + _AUDIO_CHUNK_SIZE],
                sample_rate=sample_rate,
                num_channels=num_channels,
            )
            for offset in range(0, len(audio), _AUDIO_CHUNK_SIZE)
        )
        # Trailing silence so streaming STT services and Vosk reach an end-of-utterance
        # and emit their final transcription before the pipeline is ended.
        frames.extend(
            _silence_frames(_TRAILING_SILENCE_SECONDS, sample_rate, num_channels),
        )
        frames.append(VADUserStoppedSpeakingFrame())
        return frames

    if stages[0] == LLM:
        # The user message is seeded into the LLMContext; trigger a completion.
        return [LLMRunFrame()]

    # TTS-first chain. TTSSpeakFrame (not a bare TextFrame) is the Pipecat 1.0
    # frame for standalone synthesis — a bare TextFrame's audio is dropped
    # ("unable to append audio to context") without an active LLM turn context.
    return [TTSSpeakFrame(text=event.text)]


def _silence_frames(
    seconds: float,
    sample_rate: int,
    num_channels: int,
) -> list[Frame]:
    """Build ``seconds`` of int16 mono/multi-channel silence as chunked frames."""
    silence_chunk = b'\x00' * _AUDIO_CHUNK_SIZE
    silence_bytes = int(sample_rate * seconds) * _PCM_SAMPLE_WIDTH * num_channels
    return [
        InputAudioRawFrame(
            audio=silence_chunk,
            sample_rate=sample_rate,
            num_channels=num_channels,
        )
        for _ in range(silence_bytes // _AUDIO_CHUNK_SIZE)
    ]


def _stt_needs_realtime_feed(service: object) -> bool:
    """Whether *service* must be fed paced audio with a silent lead-in.

    Cloud streaming STT (Deepgram, AssemblyAI, streaming Google) connect a
    websocket asynchronously and transcribe audio as it streams: a single burst
    is dropped before the connection is up, or yields only a partial transcript
    if a forced finalize lands before they've caught up. Feeding at real time —
    preceded by a silent lead-in so the connection establishes before any speech,
    exactly as the live mic's ambient pre-speech gap does — fixes both, with no
    dependency on a provider's private connection-ready internals.

    Segmented STT (Whisper-based: OpenAI, Venice, segmented Google) and local
    Vosk buffer a burst fine and gain nothing from pacing (which would only add
    latency), so they keep the fast burst path.
    """
    return not isinstance(service, (SegmentedSTTService, VoskSTTService))


async def _queue_stt_input_realtime(
    task: PipelineTask,
    frames: list[Frame],
    sample_rate: int,
) -> None:
    """Queue STT input frames, pacing the audio at real time.

    Streaming STT services (e.g. Deepgram) process audio as it arrives and return
    only a partial transcript if a forced finalize lands before they've caught up
    with a burst. Feeding audio at its natural rate — as the live pipeline's mic
    does — makes them transcribe the whole utterance. Segmented/local STT just
    buffer the paced audio, so this is safe for every provider.
    """
    for frame in frames:
        await task.queue_frame(frame)
        if isinstance(frame, InputAudioRawFrame):
            samples = len(frame.audio) / (_PCM_SAMPLE_WIDTH * frame.num_channels)
            await asyncio.sleep(samples / sample_rate)


async def _run_request(  # noqa: C901, PLR0912, PLR0915
    client: UboRPCClient,
    event: AssistantRunPipelineEvent,
    system_prompt_watcher: SystemPromptWatcher,
) -> None:
    """Build and run a single parametrized request pipeline."""
    session_id = event.session_id
    # First-output timeouts are overridable via env so the provider e2e tests can
    # bound each request tightly (a healthy provider responds quickly); production
    # keeps the longer defaults for slow networks / cold model loads.
    first_output_timeout = _env_float(
        'UBO_ASSISTANT_FIRST_OUTPUT_TIMEOUT_SECS',
        _FIRST_OUTPUT_TIMEOUT_SECS,
    )
    stt_flush_timeout = _env_float(
        'UBO_ASSISTANT_STT_FLUSH_TIMEOUT_SECS',
        _STT_FLUSH_TIMEOUT_SECS,
    )
    stt_quiescence = _env_float(
        'UBO_ASSISTANT_STT_QUIESCENCE_SECS',
        _STT_QUIESCENCE_SECS,
    )
    run_task_backstop = _env_float(
        'UBO_ASSISTANT_RUN_TASK_BACKSTOP_SECS',
        _RUN_TASK_BACKSTOP_SECS,
    )
    cancel_grace = _env_float(
        'UBO_ASSISTANT_CANCEL_GRACE_SECS',
        _CANCEL_GRACE_SECS,
    )
    leading_silence = _env_float(
        'UBO_ASSISTANT_LEADING_SILENCE_SECS',
        _LEADING_SILENCE_SECONDS,
    )
    stages = [
        _STAGE_IDS[stage.name] for stage in event.stages if stage.name in _STAGE_IDS
    ]
    terminal_stage = stages[-1] if stages else STT
    message = (
        f'screen-reader: run request session={session_id!r} stages={stages} '
        f'tts_provider={event.tts_provider.name!r}'
    )
    logger.info(message)
    collector = GRPCTerminalCollector(
        client=client,
        session_id=session_id,
        # The collector routes by enum identity; convert from the internal
        # string id (lowercased name) to the enum once, at the boundary.
        terminal_stage=AssistantPipelineStage[terminal_stage.upper()],
    )

    try:
        validate_stage_chain(stages)
    except ValueError as exception:
        await collector.dispatch_error(str(exception))
        return

    stage_services, error = await _resolve_stage_services(stages, event, client)
    if error is not None:
        await collector.dispatch_error(error)
        return

    context_aggregator: LLMContextAggregatorPair | None = None
    if LLM in stages:
        # One-shot requests get no tools, so the tool instructions are omitted.
        # A caller-supplied prompt still wins over the user's selection.
        system_prompt = event.system_prompt or system_prompt_watcher.compose(
            include_tools=False,
        )
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

    @task.event_handler('on_pipeline_error')
    async def _on_pipeline_error(_task: object, frame: ErrorFrame) -> None:
        if is_transient_error(frame):
            # A websocket provider dropped an idle connection and pipecat is
            # already reconnecting. Failing the request here would abort a
            # request that is about to recover; let it run on and fall back to
            # the first-output timeout if the output really never arrives.
            logger.debug(
                'Ignoring transient provider error in request pipeline {extra}',
                extra={'error': frame.error},
            )
            return
        # Surface provider errors (bad model, 401, unreachable host, …) as a real
        # error frame instead of letting them fall through to a misleading
        # "produced no output (provider timeout)". dispatch_error also sets the
        # last-output event, so the request finishes immediately rather than
        # waiting out the first-output timeout.
        await collector.dispatch_error(frame.error)

    run_task = asyncio.create_task(runner.run(task))
    try:
        stt_service = stage_services.get(STT) if stages[0] == STT else None
        # Cloud streaming STT (Deepgram, AssemblyAI, …) connect a websocket
        # asynchronously and transcribe audio as it streams, so a single burst is
        # dropped before the connection is up or yields a partial transcript at
        # finalize. Feed them at real time behind a silent lead-in — which lets
        # the connection establish before any speech, mirroring a live mic's
        # ambient pre-speech gap. Local/segmented STT (Vosk, Whisper-based) buffer
        # a burst fine, so they skip the (slower) pacing. See
        # ``_stt_needs_realtime_feed``.
        if stt_service is not None and _stt_needs_realtime_feed(stt_service):
            sample_rate = event.sample_rate or 16000
            await _queue_stt_input_realtime(
                task,
                [
                    *_silence_frames(
                        leading_silence,
                        sample_rate,
                        event.num_channels or 1,
                    ),
                    *_build_input_frames(stages, event),
                ],
                sample_rate,
            )
        else:
            await task.queue_frames(_build_input_frames(stages, event))
        if stages[0] == STT:
            try:
                await asyncio.wait_for(
                    collector.first_output.wait(),
                    timeout=stt_flush_timeout,
                )
            except TimeoutError:
                logger.warning(
                    'STT produced no output before flush timeout',
                    extra={'session_id': session_id},
                )
            else:
                # Collect the COMPLETE transcript before EndFrame/disconnect.
                # Prefer the provider's deterministic finalize signal (Deepgram's
                # from_finalize, or segmented services); otherwise fall back to
                # quiescence — keep waiting while new output keeps arriving.
                last_count = -1
                while (
                    not collector.stt_finalized.is_set()
                    and collector.output_count != last_count
                ):
                    last_count = collector.output_count
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(
                            collector.stt_finalized.wait(),
                            timeout=stt_quiescence,
                        )
        await task.queue_frame(EndFrame())
        message = (
            f'screen-reader: EndFrame queued, awaiting first output '
            f'session={session_id!r}'
        )
        logger.info(message)
        # Wait for the FIRST output frame, not the whole run — but also wake if the
        # run task finishes/crashes first, so a runner crash is noticed promptly
        # (and surfaced from the ``finally``) instead of looking like a timeout. A
        # provider the one-shot can't drive (e.g. websocket TTS) never produces
        # output, so the timeout still bounds the hang.
        first_output_waiter = asyncio.ensure_future(collector.first_output.wait())
        try:
            await asyncio.wait(
                {first_output_waiter, run_task},
                timeout=first_output_timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            first_output_waiter.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await first_output_waiter
        if collector.first_output.is_set():
            # Output is flowing — finish as soon as the terminal stage signals its
            # last frame, OR the run task ends/crashes (don't wait on the run task
            # to *unwind*: some websocket services idle for a long time after
            # delivering everything). Racing run_task here means a crash after the
            # first frame is surfaced from the ``finally`` immediately instead of
            # holding the slot for the full backstop. The backstop still bounds a
            # provider that stalls without ever sending a last frame.
            last_output_waiter = asyncio.ensure_future(collector.last_output.wait())
            try:
                await asyncio.wait(
                    {last_output_waiter, run_task},
                    timeout=run_task_backstop,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                last_output_waiter.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await last_output_waiter
            if collector.last_output.is_set():
                complete_message = (
                    f'screen-reader: output complete session={session_id!r}'
                )
                logger.info(complete_message)
            # else: the run task ended/crashed or the backstop elapsed — the
            # ``finally`` cancels it and surfaces any exception.
        else:
            # No output: timed out, or the run task ended/crashed without producing
            # anything. The ``finally`` cancels the run task (releasing the
            # concurrency slot) and reports a crash if there was one.
            message = (
                f'screen-reader: no output within '
                f'{first_output_timeout:.0f}s; cancelling '
                f'session={session_id!r} '
                f'tts_provider={event.tts_provider.name!r}'
            )
            logger.error(message)
    except Exception:
        message = (
            f'screen-reader: error running request pipeline session={session_id!r}'
        )
        logger.exception(message)
        await collector.dispatch_error('Internal error while running the pipeline')
        return
    finally:
        # Release the caller's concurrency slot promptly. Cancel the run task and
        # give it a brief grace to unwind, but DON'T await it to completion:
        # some websocket services (e.g. ElevenLabs/Rime TTS) ignore cancellation
        # during their disconnect cleanup, and ``wait_for`` awaits the task to
        # finish cancelling — which would hang the handler forever. ``asyncio.wait``
        # returns after the grace whether or not the task settled; a wedged task
        # is left to leak (far better than wedging the handler).
        if not run_task.done():
            run_task.cancel()
            with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                await asyncio.wait({run_task}, timeout=cancel_grace)
        # Observe the run task's outcome so a runner crash is surfaced (not
        # swallowed as a timeout) and retrieved (no "Task exception was never
        # retrieved"). dispatch_error is idempotent — a no-op if output already
        # went out. A still-pending (leaked, uncancellable) task is skipped.
        if run_task.done() and not run_task.cancelled():
            run_exc = run_task.exception()
            if run_exc is not None:
                run_fail_message = (
                    'screen-reader: request pipeline run task failed '
                    f'session={session_id!r}: {run_exc!r}'
                )
                logger.error(run_fail_message)
                await collector.dispatch_error(
                    'Internal error while running the pipeline',
                )

    if collector.output_count == 0 and not collector.sent_last_frame:
        message = (
            f'screen-reader: pipeline produced NO output session={session_id!r} '
            f'stages={stages} tts_provider={event.tts_provider.name!r}'
        )
        logger.error(message)
        await collector.dispatch_error('Pipeline produced no output (provider timeout)')
    else:
        message = (
            f'screen-reader: pipeline produced {collector.output_count} '
            f'output frame(s) audio_bytes={collector.audio_bytes} '
            f'rate={collector.audio_rate} '
            f'tts_provider={event.tts_provider.name!r} session={session_id!r}'
        )
        logger.info(message)
        await collector.dispatch_last_frame()
        # After the drain, so the counts are final. `dispatched` short of
        # `output_count` means chunks never reached core -- the audible symptom
        # is truncated speech, and nothing else reports it.
        delivery = (
            f'screen-reader: reports dispatched={collector.reports_dispatched} '
            f'failed={collector.reports_failed} of {collector.output_count} '
            f'output frame(s) session={session_id!r}'
        )
        logger.info(delivery)
