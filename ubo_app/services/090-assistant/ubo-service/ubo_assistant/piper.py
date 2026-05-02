"""Vosk speech to text service for pipecat."""

import asyncio
from collections.abc import AsyncGenerator, Sequence
from concurrent.futures import ThreadPoolExecutor

from loguru import logger
from pipecat.frames.frames import (
    ErrorFrame,
    Frame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService
from pipecat.transcriptions.language import Language
from pipecat.utils.text.base_text_filter import BaseTextFilter
from pipecat.utils.tracing.service_decorators import traced_stt

from ubo_assistant.constants import DATA_PATH

PIPER_MODEL = 'en/en_US/kristin/medium/en_US-kristin-medium'
PIPER_MODEL_PATH = (DATA_PATH / PIPER_MODEL).with_suffix('.onnx')


class PiperTTSService(TTSService):
    """Vosk speech to text service for pipecat."""

    STREAMING_LIMIT = 120000  # 2 minutes in milliseconds
    LANGUAGE_CODE: Language = Language.EN_US

    def __init__(  # noqa: PLR0913
        self,
        *,
        aggregate_sentences: bool = True,
        push_text_frames: bool = True,
        push_stop_frames: bool = False,
        stop_frame_timeout_s: float = 2.0,
        push_silence_after_stop: bool = False,
        silence_time_s: float = 2.0,
        pause_frame_processing: bool = False,
        text_filters: Sequence[BaseTextFilter] | None = None,
        transport_destination: str | None = None,
    ) -> None:
        """Initialize vosk speech to text service."""
        self._process_executor = ThreadPoolExecutor(max_workers=1)
        self._sample_queue: asyncio.Queue[bytes | None] = asyncio.Queue()

        from piper.voice import PiperVoice

        self._client = PiperVoice.load(PIPER_MODEL_PATH)

        self.tasks: list[asyncio.Handle] = []

        super().__init__(
            aggregate_sentences=aggregate_sentences,
            push_text_frames=push_text_frames,
            push_stop_frames=push_stop_frames,
            stop_frame_timeout_s=stop_frame_timeout_s,
            push_silence_after_stop=push_silence_after_stop,
            silence_time_s=silence_time_s,
            pause_frame_processing=pause_frame_processing,
            sample_rate=self._client.config.sample_rate,
            text_filters=text_filters,
            transport_destination=transport_destination,
            settings=TTSSettings(
                model=PIPER_MODEL,
                voice='kristin',
                language=self.LANGUAGE_CODE,
            ),
        )

    def synthesize(self, text: str) -> None:
        """Synthesize audio from text."""
        for audio_chunk in self._client.synthesize(text=text):
            if audio_chunk:
                sample = audio_chunk.audio_int16_bytes
                self.tasks = [
                    *self.tasks,
                    self.get_event_loop().call_soon_threadsafe(
                        self.create_task,
                        self._sample_queue.put(sample),
                    ),
                ]
        self.tasks = [
            *self.tasks,
            self.get_event_loop().call_soon_threadsafe(
                self.create_task,
                self._sample_queue.put(None),
            ),
        ]

    @traced_stt
    async def run_tts(
        self,
        text: str,
        context_id: str,
    ) -> AsyncGenerator[Frame, None]:
        """Process an audio chunk for STT transcription."""
        _ = context_id
        try:
            await self.start_ttfb_metrics()
            await self.start_tts_usage_metrics(text)

            yield TTSStartedFrame()

            audio_buffer = b''
            first_chunk_for_ttfb = False

            self.get_event_loop().run_in_executor(
                self._process_executor,
                self.synthesize,
                text,
            )

            while (chunk := await self._sample_queue.get()) is not None:
                if not first_chunk_for_ttfb:
                    await self.stop_ttfb_metrics()
                    first_chunk_for_ttfb = True

                audio_buffer += chunk

                while len(audio_buffer) >= self.chunk_size:
                    piece = audio_buffer[: self.chunk_size]
                    audio_buffer = audio_buffer[self.chunk_size :]
                    yield TTSAudioRawFrame(piece, self.sample_rate, 1)

            yield TTSStoppedFrame()

        except Exception as e:
            logger.exception('Error generating TTS')
            error_message = f'TTS generation error: {e}'
            yield ErrorFrame(error=error_message)
