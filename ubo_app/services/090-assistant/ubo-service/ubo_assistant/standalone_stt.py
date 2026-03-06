"""Standalone STT handler for decoupled speech-to-text over gRPC."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING

from loguru import logger
from pipecat.frames.frames import (
    EndFrame,
    Frame,
    InputAudioRawFrame,
    TranscriptionFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from ubo_bindings.ubo.v1 import (
    AcceptableAssistanceFrame,
    Action,
    AssistanceErrorFrame,
    AssistanceTextFrame,
    AssistantReportAction,
    AssistantTranscribeEvent,
    Event,
)

if TYPE_CHECKING:
    from pipecat.services.stt_service import STTService
    from ubo_bindings.client import UboRPCClient

AUDIO_CHUNK_SIZE = 320
_VOSK_MODEL_TTL = 600  # 10 minutes of inactivity before evicting
_SECRETS_TTL = 300  # 5 minutes


class _VoskModelCache:
    """Lazy-loaded Vosk model with TTL-based eviction on inactivity.

    The model is kept in memory as long as Vosk remains the active STT
    provider.  When a non-Vosk provider is used the ``mark_inactive`` flag
    is set and an eviction timer starts.  A subsequent Vosk request cancels
    the timer automatically.
    """

    def __init__(self) -> None:
        self._model: object | None = None
        self._eviction_handle: asyncio.TimerHandle | None = None
        self._is_active_provider: bool = False

    def create_recognizer(self, sample_rate: int) -> object:
        """Return a KaldiRecognizer, loading the model on first call."""
        from vosk import KaldiRecognizer, Model

        from ubo_assistant.vosk import VOSK_MODEL_PATH

        if self._model is None:
            self._model = Model(model_path=VOSK_MODEL_PATH.as_posix(), lang='en-us')
        self._is_active_provider = True
        self._cancel_eviction()
        return KaldiRecognizer(self._model, sample_rate)

    def mark_inactive(self) -> None:
        """Mark Vosk as not the current provider and schedule eviction."""
        if not self._is_active_provider:
            return
        self._is_active_provider = False
        if self._model is not None:
            self._schedule_eviction()

    def _schedule_eviction(self) -> None:
        self._cancel_eviction()
        loop = asyncio.get_event_loop()
        self._eviction_handle = loop.call_later(_VOSK_MODEL_TTL, self._evict)

    def _cancel_eviction(self) -> None:
        if self._eviction_handle is not None:
            self._eviction_handle.cancel()
            self._eviction_handle = None

    def _evict(self) -> None:
        self._model = None
        self._eviction_handle = None
        logger.info('Vosk model evicted from memory due to inactivity')


_vosk_cache = _VoskModelCache()

_secrets_cache: dict[str, tuple[float, str | None]] = {}


async def _get_cached_secret(client: UboRPCClient, key: str) -> str | None:
    if not key:
        return None
    now = time.monotonic()
    if key in _secrets_cache:
        ts, value = _secrets_cache[key]
        if now - ts < _SECRETS_TTL:
            return value
    value = await client.query_secret(key)
    if value is not None:
        _secrets_cache[key] = (now, value)
    return value


class _STTOutputCollector(FrameProcessor):
    """Collects STT output frames and dispatches them via gRPC."""

    def __init__(
        self,
        client: UboRPCClient,
        session_id: str,
        assistance_id: str,
    ) -> None:
        super().__init__()
        self._client = client
        self._session_id = session_id
        self._assistance_id = assistance_id
        self.index = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process output frames from the STT service."""
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            self._client.dispatch(
                action=Action(
                    assistant_report_action=AssistantReportAction(
                        source_id='standalone_stt',
                        data=AcceptableAssistanceFrame(
                            assistance_text_frame=AssistanceTextFrame(
                                text=frame.text,
                                timestamp=self._client.event_loop.time(),
                                id=self._assistance_id,
                                index=self.index,
                                source='stt_standalone',
                                session_id=self._session_id,
                            ),
                        ),
                    ),
                ),
            )
            self.index += 1

        await self.push_frame(frame, direction)


def setup_standalone_stt(client: UboRPCClient) -> None:
    """Subscribe to AssistantTranscribeEvent and handle standalone STT requests."""
    semaphore = asyncio.Semaphore(3)

    def _handle_transcribe_event(event: Event) -> None:
        transcribe = event.assistant_transcribe_event
        if not transcribe:
            return

        async def _guarded() -> None:
            async with semaphore:
                await _process_transcription(client, transcribe)

        client.event_loop.create_task(_guarded())

    client.subscribe_event(
        event_type=Event(
            assistant_transcribe_event=AssistantTranscribeEvent(),
        ),
        callback=_handle_transcribe_event,
    )
    logger.info('Standalone STT handler registered')


async def _process_transcription(
    client: UboRPCClient,
    event: AssistantTranscribeEvent,
) -> None:
    """Process a standalone transcription request."""
    session_id = event.session_id
    assistance_id = uuid.uuid4().hex

    stt_provider = event.stt_provider
    if stt_provider is None:
        _dispatch_error(
            client,
            session_id=session_id,
            assistance_id=assistance_id,
            error='No STT provider specified',
        )
        return

    stt_name = (stt_provider.name or '').lower()

    try:
        sample_rate = event.sample_rate or 16000
        num_channels = event.num_channels or 1
        audio = event.audio
        index = 0

        if stt_name == 'vosk':
            # Vosk batch processing: use KaldiRecognizer directly.
            # The pipeline approach doesn't work for Vosk because its
            # streaming task gets killed by EndFrame before producing
            # a final result.
            index = await _process_vosk_batch(
                client,
                audio=audio,
                sample_rate=sample_rate,
                session_id=session_id,
                assistance_id=assistance_id,
            )
        else:
            _vosk_cache.mark_inactive()
            stt_service = await _create_stt_service(client, stt_name)

            if stt_service is None:
                _dispatch_error(
                    client,
                    session_id=session_id,
                    assistance_id=assistance_id,
                    error=(
                        f"STT provider '{stt_name}' is not configured"
                        ' or unavailable'
                    ),
                )
                return

            # Create output collector
            collector = _STTOutputCollector(
                client=client,
                session_id=session_id,
                assistance_id=assistance_id,
            )

            # Build and run a mini pipeline
            pipeline = Pipeline([stt_service, collector])
            task = PipelineTask(
                pipeline,
                params=PipelineParams(),
            )
            runner = PipelineRunner(handle_sigint=False)

            # Build audio frames
            audio_frames: list[Frame] = []
            for i in range(0, len(audio), AUDIO_CHUNK_SIZE):
                chunk = audio[i : i + AUDIO_CHUNK_SIZE]
                audio_frames.append(
                    InputAudioRawFrame(
                        audio=chunk,
                        sample_rate=sample_rate,
                        num_channels=num_channels,
                    ),
                )

            # Start the pipeline in the background, feed audio, then end
            run_task = asyncio.create_task(runner.run(task))
            await task.queue_frames([*audio_frames, EndFrame()])
            await run_task
            index = collector.index

        # Send final frame (skip for Vosk when it already sent is_last_frame)
        if not (stt_name == 'vosk' and index > 0):
            client.dispatch(
                action=Action(
                    assistant_report_action=AssistantReportAction(
                        source_id='standalone_stt',
                        data=AcceptableAssistanceFrame(
                            assistance_text_frame=AssistanceTextFrame(
                                text='',
                                timestamp=client.event_loop.time(),
                                id=assistance_id,
                                index=index,
                                source='stt_standalone',
                                session_id=session_id,
                                is_last_frame=True,
                            ),
                        ),
                    ),
                ),
            )

    except Exception:
        logger.exception(
            'Error in standalone STT',
            extra={'session_id': session_id},
        )
        _dispatch_error(
            client,
            session_id=session_id,
            assistance_id=assistance_id,
            error='Internal error during transcription',
        )


async def _process_vosk_batch(
    client: UboRPCClient,
    *,
    audio: bytes,
    sample_rate: int,
    session_id: str,
    assistance_id: str,
) -> int:
    """Process audio with Vosk KaldiRecognizer directly (batch mode).

    Returns the number of text frames dispatched.
    """
    import json

    rec = _vosk_cache.create_recognizer(sample_rate)

    # Feed all audio to the recognizer (vosk types not available at typecheck)
    await asyncio.to_thread(rec.AcceptWaveform, audio)  # pyright: ignore[reportAttributeAccessIssue]

    # Get the final transcription
    raw = await asyncio.to_thread(rec.FinalResult)  # pyright: ignore[reportAttributeAccessIssue]
    text = json.loads(raw).get('text', '')

    index = 0
    if text:
        client.dispatch(
            action=Action(
                assistant_report_action=AssistantReportAction(
                    source_id='standalone_stt',
                    data=AcceptableAssistanceFrame(
                        assistance_text_frame=AssistanceTextFrame(
                            text=text,
                            timestamp=client.event_loop.time(),
                            id=assistance_id,
                            index=index,
                            source='stt_standalone',
                            session_id=session_id,
                            is_last_frame=True,
                        ),
                    ),
                ),
            ),
        )
        index += 1

    return index


async def _create_stt_service(
    client: UboRPCClient,
    stt_name: str,
) -> STTService | None:
    """Create a standalone STT service instance for the given provider."""
    import os

    if stt_name == 'openai':
        from pipecat.services.openai.stt import OpenAISTTService

        api_key = await _get_cached_secret(client,
            os.environ.get('OPENAI_API_KEY_SECRET_ID', ''),
        )
        if api_key:
            return OpenAISTTService(api_key=api_key)
        return None

    if stt_name in ('google', 'google_segmented'):
        credentials = await _get_cached_secret(client,
            os.environ.get('GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID', ''),
        )
        if credentials:
            if stt_name == 'google_segmented':
                from ubo_assistant.segmented_googlestt import (
                    SegmentedGoogleSTTService,
                )

                return SegmentedGoogleSTTService(
                    credentials=credentials,
                    model='long',
                    sample_rate=16000,
                )
            from pipecat.services.google.stt import GoogleSTTService

            return GoogleSTTService(
                credentials=credentials,
                model='long',
                sample_rate=16000,
            )
        return None

    if stt_name == 'deepgram':
        from deepgram import LiveOptions
        from pipecat.services.deepgram.stt import DeepgramSTTService

        api_key = await _get_cached_secret(client,
            os.environ.get('DEEPGRAM_API_KEY_SECRET_ID', ''),
        )
        if api_key:
            return DeepgramSTTService(
                api_key=api_key,
                live_options=LiveOptions(
                    model='nova-3',
                    language='multi',
                    smart_format=True,
                ),
            )
        return None

    if stt_name == 'assemblyai':
        from pipecat.services.assemblyai.models import AssemblyAIConnectionParams
        from pipecat.services.assemblyai.stt import AssemblyAISTTService

        api_key = await _get_cached_secret(client,
            os.environ.get('ASSEMBLYAI_API_KEY_SECRET_ID', ''),
        )
        if api_key:
            return AssemblyAISTTService(
                api_key=api_key,
                vad_force_turn_endpoint=False,
                connection_params=AssemblyAIConnectionParams(
                    end_of_turn_confidence_threshold=0.7,
                    min_end_of_turn_silence_when_confident=160,
                    max_turn_silence=2400,
                ),
            )
        return None

    return None


def _dispatch_error(
    client: UboRPCClient,
    *,
    session_id: str,
    assistance_id: str,
    error: str,
) -> None:
    """Dispatch an error frame back to core."""
    client.dispatch(
        action=Action(
            assistant_report_action=AssistantReportAction(
                source_id='standalone_stt',
                data=AcceptableAssistanceFrame(
                    assistance_error_frame=AssistanceErrorFrame(
                        error=error,
                        timestamp=client.event_loop.time(),
                        id=assistance_id,
                        index=0,
                        session_id=session_id,
                        is_last_frame=True,
                    ),
                ),
            ),
        ),
    )
