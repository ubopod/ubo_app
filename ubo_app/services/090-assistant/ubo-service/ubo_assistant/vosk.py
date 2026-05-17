"""Vosk speech to text service for pipecat."""

import asyncio
import json
import time
from collections.abc import AsyncGenerator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

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
from pipecat.services.settings import STTSettings
from pipecat.services.stt_service import STTService
from pipecat.transcriptions.language import Language
from pipecat.utils.time import time_now_iso8601
from pipecat.utils.tracing.service_decorators import traced_stt
from vosk import KaldiRecognizer, Model

from ubo_assistant.constants import DATA_PATH

DEFAULT_VOSK_MODEL_ID = 'vosk-model-small-en-us-0.15'


def _model_path(model_id: str) -> Path:
    """Build the on-disk path for *model_id*'s expanded model directory."""
    return DATA_PATH / model_id


class VoskSTTService(STTService):
    """Vosk speech to text service for pipecat."""

    STREAMING_LIMIT = 120000  # 2 minutes in milliseconds
    LANGUAGE_CODE: Language = Language.EN_US

    def __init__(
        self,
        audio_passthrough=True,  # noqa: ANN001, FBT002
        sample_rate: int | None = None,
        model_id: str = DEFAULT_VOSK_MODEL_ID,
    ) -> None:
        """Initialize vosk speech to text service."""
        super().__init__(
            audio_passthrough=audio_passthrough,
            sample_rate=sample_rate,
            settings=STTSettings(model=model_id, language=self.LANGUAGE_CODE),
            ttfs_p99_latency=1.0,
        )
        self._process_executor = ThreadPoolExecutor(max_workers=1)
        self._request_queue = asyncio.Queue()
        self._streaming_task = None
        # Lock serialises model loads against in-flight transcription so a
        # mid-stream model switch never tears the queue.
        self._reload_lock = asyncio.Lock()
        # ``_requested_model_id`` is the model the user wants (updated by
        # ``request_model`` from the store autorun callback — possibly on a
        # foreign thread, so it's a plain attribute write and nothing more).
        # ``_loaded_model_id`` is what's actually in ``_client``. ``run_stt``
        # reconciles the two before every chunk, so a missed signal or a
        # not-yet-downloaded model self-heals on the next utterance instead
        # of needing the user to toggle repeatedly.
        self._requested_model_id = model_id
        self._loaded_model_id = model_id
        model = Model(model_path=_model_path(model_id).as_posix())
        self._client = KaldiRecognizer(model, 16000)

    def request_model(self, model_id: str) -> None:
        """Record the Vosk model the user selected.

        Deliberately does no work beyond a single attribute write so it
        is safe to call from any thread (the store autorun callback runs
        off the pipeline event loop). The model load itself is deferred
        to ``_ensure_model_loaded``, which ``run_stt`` invokes before
        every audio chunk.
        """
        if not model_id:
            return
        self._requested_model_id = model_id

    async def _ensure_model_loaded(self) -> None:
        """Load ``_requested_model_id`` if it differs from what's loaded.

        Must be called while holding ``_reload_lock``. No-op when the
        requested model is already current, or when it isn't on disk yet
        (the core process downloads it; the next chunk retries).
        """
        model_id = self._requested_model_id
        if model_id == self._loaded_model_id:
            return

        path = _model_path(model_id)
        if not path.exists():
            logger.warning(
                'Requested Vosk model not downloaded yet; keeping current',
                extra={
                    'requested_model_id': model_id,
                    'loaded_model_id': self._loaded_model_id,
                    'path': str(path),
                },
            )
            return

        try:
            new_model = await asyncio.get_running_loop().run_in_executor(
                self._process_executor,
                lambda: Model(model_path=path.as_posix()),
            )
        except Exception:
            logger.exception(
                'Failed to load Vosk model',
                extra={'model_id': model_id, 'path': str(path)},
            )
            return

        self._client = KaldiRecognizer(new_model, 16000)
        self._loaded_model_id = model_id
        self._settings = STTSettings(  # pyright: ignore[reportAttributeAccessIssue]
            model=model_id,
            language=self.LANGUAGE_CODE,
        )
        logger.info(
            'Loaded Vosk model',
            extra={'model_id': model_id},
        )

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
            # Reconcile the loaded model with the user's selection *before*
            # queueing — this is the single point where a model switch
            # actually takes effect.
            async with self._reload_lock:
                await self._ensure_model_loaded()
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
