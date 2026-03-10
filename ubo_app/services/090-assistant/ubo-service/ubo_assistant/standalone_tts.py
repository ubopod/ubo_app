"""Standalone TTS handler for decoupled text-to-speech over gRPC."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING

from loguru import logger
from pipecat.frames.frames import (
    EndFrame,
    Frame,
    TextFrame,
    TTSAudioRawFrame,
    TTSStoppedFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from ubo_bindings.ubo.v1 import (
    AcceptableAssistanceFrame,
    Action,
    AssistanceAudioFrame,
    AssistanceErrorFrame,
    AssistanceTextFrame,
    AssistantReportAction,
    AssistantSynthesizeEvent,
    AudioSample,
    Event,
)

if TYPE_CHECKING:
    from pipecat.services.tts_service import TTSService
    from ubo_bindings.client import UboRPCClient

_secrets_cache: dict[str, tuple[float, str | None]] = {}
_SECRETS_TTL = 300  # 5 minutes


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


class _TTSOutputCollector(FrameProcessor):
    """Collects TTS output frames and dispatches them via gRPC."""

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
        self._index = 0
        self._sent_last_frame = False

    @property
    def sent_last_frame(self) -> bool:
        """Whether an end-of-stream marker has been dispatched."""
        return self._sent_last_frame

    def dispatch_last_frame(self) -> None:
        """Dispatch a final marker frame exactly once."""
        if self._sent_last_frame:
            return
        self._client.dispatch(
            action=Action(
                assistant_report_action=AssistantReportAction(
                    source_id='standalone_tts',
                    data=AcceptableAssistanceFrame(
                        assistance_text_frame=AssistanceTextFrame(
                            text='',
                            timestamp=self._client.event_loop.time(),
                            id=self._assistance_id,
                            index=self._index,
                            source='tts_standalone',
                            session_id=self._session_id,
                            is_last_frame=True,
                        ),
                    ),
                ),
            ),
        )
        self._sent_last_frame = True

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process output frames from the TTS service."""
        await super().process_frame(frame, direction)

        if isinstance(frame, TTSAudioRawFrame) and frame.audio:
            self._client.dispatch(
                action=Action(
                    assistant_report_action=AssistantReportAction(
                        source_id='standalone_tts',
                        data=AcceptableAssistanceFrame(
                            assistance_audio_frame=AssistanceAudioFrame(
                                audio=AudioSample(
                                    data=frame.audio,
                                    rate=frame.sample_rate,
                                    channels=frame.num_channels,
                                    width=2,
                                ),
                                timestamp=self._client.event_loop.time(),
                                id=self._assistance_id,
                                index=self._index,
                                session_id=self._session_id,
                            ),
                        ),
                    ),
                ),
            )
            self._index += 1

        elif isinstance(frame, TTSStoppedFrame):
            self.dispatch_last_frame()

        await self.push_frame(frame, direction)


def setup_standalone_tts(client: UboRPCClient) -> None:
    """Subscribe to AssistantSynthesizeEvent and handle standalone TTS requests."""
    semaphore = asyncio.Semaphore(3)

    def _handle_synthesize_event(event: Event) -> None:
        synthesize = event.assistant_synthesize_event
        if not synthesize:
            return

        async def _guarded() -> None:
            async with semaphore:
                await _process_synthesis(client, synthesize)

        client.event_loop.create_task(_guarded())

    client.subscribe_event(
        event_type=Event(
            assistant_synthesize_event=AssistantSynthesizeEvent(),
        ),
        callback=_handle_synthesize_event,
    )
    logger.info('Standalone TTS handler registered')


async def _process_synthesis(
    client: UboRPCClient,
    event: AssistantSynthesizeEvent,
) -> None:
    """Process a standalone TTS synthesis request."""
    session_id = event.session_id
    assistance_id = uuid.uuid4().hex

    tts_provider = event.tts_provider
    if tts_provider is None:
        _dispatch_error(
            client,
            session_id=session_id,
            assistance_id=assistance_id,
            error='No TTS provider specified',
        )
        return

    tts_name = (tts_provider.name or '').lower()

    try:
        tts_service = await _create_tts_service(client, tts_name)

        if tts_service is None:
            _dispatch_error(
                client,
                session_id=session_id,
                assistance_id=assistance_id,
                error=f"TTS provider '{tts_name}' is not configured or unavailable",
            )
            return

        # Create output collector
        collector = _TTSOutputCollector(
            client=client,
            session_id=session_id,
            assistance_id=assistance_id,
        )

        # Build and run a mini pipeline
        pipeline = Pipeline([tts_service, collector])
        task = PipelineTask(
            pipeline,
            params=PipelineParams(),
        )
        runner = PipelineRunner(handle_sigint=False)

        # Queue the text frame and end frame to the pipeline
        await task.queue_frames(
            [TextFrame(text=event.text), EndFrame()],
        )

        await runner.run(task)
        collector.dispatch_last_frame()

    except Exception:
        logger.exception(
            'Error in standalone TTS',
            extra={'session_id': session_id},
        )
        _dispatch_error(
            client,
            session_id=session_id,
            assistance_id=assistance_id,
            error='Internal error during synthesis',
        )


async def _create_tts_service(
    client: UboRPCClient,
    tts_name: str,
) -> TTSService | None:
    """Create a standalone TTS service instance for the given provider."""
    import os

    if tts_name == 'piper':
        from ubo_assistant.piper import PiperTTSService

        return PiperTTSService()

    if tts_name == 'google':
        from pipecat.services.google.tts import GoogleTTSService

        credentials = await _get_cached_secret(client,
            os.environ.get('GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID', ''),
        )
        if credentials:
            return GoogleTTSService(credentials=credentials)
        return None

    if tts_name == 'openai':
        from pipecat.services.openai.tts import OpenAITTSService

        api_key = await _get_cached_secret(client,
            os.environ.get('OPENAI_API_KEY_SECRET_ID', ''),
        )
        if api_key:
            return OpenAITTSService(api_key=api_key)
        return None

    if tts_name == 'elevenlabs':
        from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

        api_key = await _get_cached_secret(client,
            os.environ.get('ELEVENLABS_API_KEY_SECRET_ID', ''),
        )
        voice_id = await _get_cached_secret(client,
            os.environ.get('ELEVENLABS_VOICE_ID', ''),
        )
        if api_key and voice_id:
            return ElevenLabsTTSService(
                api_key=api_key,
                voice_id=voice_id,
                sample_rate=24000,
                model='eleven_turbo_v2_5',
            )
        return None

    if tts_name == 'rime':
        from pipecat.services.rime.tts import RimeTTSService
        from pipecat.transcriptions.language import Language

        api_key = await _get_cached_secret(client,
            os.environ.get('RIME_API_KEY_SECRET_ID', ''),
        )
        if api_key:
            return RimeTTSService(
                api_key=api_key,
                voice_id='antoine',
                model='mistv2',
                params=RimeTTSService.InputParams(
                    language=Language.EN,
                    speed_alpha=1.0,
                    reduce_latency=False,
                    pause_between_brackets=True,
                    phonemize_between_brackets=False,
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
                source_id='standalone_tts',
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
