"""Vosk speech to text service for pipecat."""

import asyncio
import json
import time
from collections.abc import AsyncGenerator
from concurrent.futures import ThreadPoolExecutor

from loguru import logger
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    InterimTranscriptionFrame,
    StartFrame,
    TranscriptionFrame,
)
from pipecat.services.stt_service import STTService
from pipecat.transcriptions.language import Language
from pipecat.utils.time import time_now_iso8601
from pipecat.utils.tracing.service_decorators import traced_stt
from vosk import KaldiRecognizer, Model

from ubo_assistant.constants import DATA_PATH

VOSK_MODEL = 'vosk-model-small-en-us-0.15'
VOSK_MODEL_PATH = DATA_PATH / VOSK_MODEL


class VoskSTTService(STTService):
    """Vosk speech to text service for pipecat."""

    STREAMING_LIMIT = 120000  # 2 minutes in milliseconds
    LANGUAGE_CODE: Language = Language.EN_US

    def __init__(
        self,
        audio_passthrough=True,  # noqa: ANN001, FBT002
        sample_rate: int | None = None,
        **kwargs: object,
    ) -> None:
        """Initialize vosk speech to text service."""
        super().__init__(audio_passthrough, sample_rate, **kwargs)
        self._process_executor = ThreadPoolExecutor(max_workers=1)
        self._request_queue = asyncio.Queue()
        self._streaming_task = None
        model = Model(
            model_path=VOSK_MODEL_PATH.as_posix(),
            lang='en-us',
        )
        self._client = KaldiRecognizer(model, 16000)

    async def start(self, frame: StartFrame) -> None:
        """Start the background running engine task."""
        await super().start(frame)
        self._stream_start_time = int(time.time() * 1000)
        self._streaming_task = self.create_task(self._stream_audio())

    async def stop(self, frame: EndFrame) -> None:
        """Stop the background running engine task."""
        await super().stop(frame)
        await self.clear()

    async def cancel(self, frame: CancelFrame) -> None:
        """Cancel the background running engine task."""
        await super().cancel(frame)
        await self.clear()

    async def clear(self) -> None:
        """Stop streaming."""
        if self._streaming_task:
            await self.cancel_task(self._streaming_task)

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Process an audio chunk for STT transcription."""
        if self._streaming_task:
            # Queue the audio data
            await self.start_ttfb_metrics()
            await self.start_processing_metrics()
            await self._request_queue.put(audio)
        yield None

    @traced_stt
    async def _handle_transcription(
        self,
        transcript: str,
        is_final: bool,  # noqa: FBT001
        language: str | None = None,
    ) -> None:
        _ = transcript, is_final, language

    async def _stream_audio(self) -> None:
        """Handle bi-directional streaming with Vosk STT."""
        try:
            while True:
                # Process responses
                await self._process_responses()

                # If we're here, check if we need to reconnect
                if (
                    int(time.time() * 1000) - self._stream_start_time
                ) > self.STREAMING_LIMIT:
                    logger.info('Reconnecting stream after timeout')
                    # Reset stream start time
                    self._stream_start_time = int(time.time() * 1000)
                    continue
                # Normal stream end
                break

        except Exception as exception:
            logger.exception('Error in streaming task')
            await self.push_frame(ErrorFrame(str(exception)))

    async def _process_responses(self) -> None:
        """Process streaming recognition responses."""
        try:
            while True:
                if not self._task_manager:
                    await asyncio.sleep(0.05)
                    continue

                data = await self._request_queue.get()
                if (
                    int(time.time() * 1000) - self._stream_start_time
                ) > self.STREAMING_LIMIT:
                    logger.info('Stream timeout reached in response processing')
                    break

                result = await self._task_manager.get_event_loop().run_in_executor(
                    self._process_executor,
                    self._client.AcceptWaveform,
                    data,
                )

                if result < 0:
                    await asyncio.sleep(0.05)
                    continue

                is_final = result > 0

                if is_final:
                    transcript = json.loads(self._client.FinalResult()).get('text')
                else:
                    transcript = json.loads(self._client.PartialResult()).get('partial')

                if not transcript:
                    continue

                if is_final:
                    await self.push_frame(
                        TranscriptionFrame(
                            transcript,
                            '',
                            time_now_iso8601(),
                            self.LANGUAGE_CODE,
                            result=result,
                        ),
                    )
                    await self.stop_processing_metrics()
                    await self._handle_transcription(
                        transcript,
                        is_final=True,
                        language=self.LANGUAGE_CODE,
                    )
                else:
                    await self.stop_ttfb_metrics()
                    await self.push_frame(
                        InterimTranscriptionFrame(
                            transcript,
                            '',
                            time_now_iso8601(),
                            self.LANGUAGE_CODE,
                            result=result,
                        ),
                    )

        except Exception:
            logger.exception('Error processing Vosk STT responses')

            # Re-raise the exception to let it propagate
            raise
