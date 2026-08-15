"""Piper text-to-speech service for pipecat."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

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
from pipecat.utils.tracing.service_decorators import traced_stt

from ubo_assistant.constants import DATA_PATH

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Sequence
    from pathlib import Path

    from pipecat.utils.text.base_text_filter import BaseTextFilter
    from piper.voice import PiperVoice

DEFAULT_PIPER_VOICE_ID = 'en/en_US/kristin/medium/en_US-kristin-medium'

# Placeholder sample rate used before any voice model is loaded. Piper
# "medium"/"high" voices (including the default ``kristin/medium``) are
# 22050 Hz; ``_ensure_voice_loaded`` overwrites ``_sample_rate`` from the real
# model the moment one is loaded, so this only applies pre-first-load.
_DEFAULT_SAMPLE_RATE = 22050


def _voice_path(voice_id: str) -> Path:
    """Build the on-disk path for *voice_id*'s ``.onnx`` model file."""
    return (DATA_PATH / voice_id).with_suffix('.onnx')


def _speaker_for(voice_id: str) -> str:
    """Extract a display-style speaker name from a HuggingFace voice id."""
    parts = voice_id.split('/')
    return parts[2] if len(parts) >= 3 else voice_id  # noqa: PLR2004


class PiperTTSService(TTSService):
    """Piper text-to-speech service for pipecat."""

    STREAMING_LIMIT = 120000  # 2 minutes in milliseconds
    LANGUAGE_CODE: Language = Language.EN_US

    def __init__(  # noqa: PLR0913
        self,
        *,
        voice_id: str = DEFAULT_PIPER_VOICE_ID,
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
        """Initialize the Piper service with *voice_id* loaded from disk."""
        self._process_executor = ThreadPoolExecutor(max_workers=1)
        self._sample_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        # Lock serialises model loads against in-flight synthesis so a
        # mid-utterance voice switch never tears the queue.
        self._reload_lock = asyncio.Lock()

        # ``_requested_voice_id`` is the voice the user wants (updated by
        # ``request_voice`` from the store autorun callback — possibly on
        # a foreign thread, so it's a plain attribute write and nothing
        # more). ``_loaded_voice_id`` is what's actually in ``_client``.
        # ``run_tts`` reconciles the two before every utterance, so a
        # missed signal or a not-yet-downloaded voice self-heals on the
        # next turn instead of needing the user to toggle repeatedly.
        #
        # Construction NEVER touches the weights, even when the voice file is
        # already on disk. A loaded Piper voice costs ~94 MB resident, and this
        # service is constructed at subprocess start for every user regardless
        # of which TTS provider they selected — so loading here charged that
        # memory to people who never synthesize a word locally.
        # ``_ensure_voice_loaded`` does the load before the first utterance,
        # which is also what makes a freshly-downloaded voice work without a
        # restart.
        self._requested_voice_id = voice_id
        self._loaded_voice_id: str | None = None
        self._client: PiperVoice | None = None
        sample_rate = _DEFAULT_SAMPLE_RATE

        self.tasks: list[asyncio.Handle] = []

        super().__init__(
            aggregate_sentences=aggregate_sentences,
            push_text_frames=push_text_frames,
            push_stop_frames=push_stop_frames,
            stop_frame_timeout_s=stop_frame_timeout_s,
            push_silence_after_stop=push_silence_after_stop,
            silence_time_s=silence_time_s,
            pause_frame_processing=pause_frame_processing,
            sample_rate=sample_rate,
            text_filters=text_filters,
            transport_destination=transport_destination,
            settings=TTSSettings(
                model=voice_id,
                voice=_speaker_for(voice_id),
                language=self.LANGUAGE_CODE,
            ),
        )

    def request_voice(self, voice_id: str) -> None:
        """Record the voice the user selected.

        Deliberately does no work beyond a single attribute write so it
        is safe to call from any thread (the store autorun callback runs
        off the pipeline event loop). The model load itself is deferred
        to ``_ensure_voice_loaded``, which ``run_tts`` invokes before
        every utterance.
        """
        if not voice_id:
            return
        self._requested_voice_id = voice_id

    async def _ensure_voice_loaded(self) -> None:
        """Load ``_requested_voice_id`` if it differs from what's loaded.

        Must be called while holding ``_reload_lock``. No-op when the
        requested voice is already current, or when it isn't on disk yet
        (the core process downloads it; the next utterance retries).
        """
        voice_id = self._requested_voice_id
        if voice_id == self._loaded_voice_id:
            return

        model_path = _voice_path(voice_id)
        if not model_path.exists():
            logger.warning(
                'Requested Piper voice not downloaded yet; keeping current',
                extra={
                    'requested_voice_id': voice_id,
                    'loaded_voice_id': self._loaded_voice_id,
                    'path': str(model_path),
                },
            )
            return

        from piper.voice import PiperVoice

        try:
            new_client = await asyncio.get_running_loop().run_in_executor(
                self._process_executor,
                lambda: PiperVoice.load(model_path),
            )
        except Exception:
            logger.exception(
                'Failed to load Piper voice',
                extra={'voice_id': voice_id, 'path': str(model_path)},
            )
            return

        self._client = new_client
        self._loaded_voice_id = voice_id
        self._sample_rate = new_client.config.sample_rate
        self._settings = TTSSettings(  # pyright: ignore[reportAttributeAccessIssue]
            model=voice_id,
            voice=_speaker_for(voice_id),
            language=self.LANGUAGE_CODE,
        )
        logger.info(
            'Loaded Piper voice',
            extra={'voice_id': voice_id},
        )

    async def unload(self) -> bool:
        """Drop the loaded voice model, returning ~94 MB to the allocator.

        Called when the user switches to another TTS provider — keeping a
        voice resident for the life of the subprocess is what made "try Piper
        once" a permanent cost. ``run_tts`` reloads on the next utterance, so
        this is safe to call at any time.

        Takes ``_reload_lock`` so an unload can never tear a synthesis that is
        already streaming. Returns whether anything was actually released.
        """
        async with self._reload_lock:
            if self._client is None:
                return False

            logger.info(
                'Unloading Piper voice',
                extra={'voice_id': self._loaded_voice_id},
            )
            self._client = None
            self._loaded_voice_id = None
            return True

    def synthesize(self, text: str) -> None:
        """Synthesize audio from text."""
        if self._client is None:
            # No voice loaded yet (none downloaded). Signal end-of-stream so
            # the consumer in ``run_tts`` doesn't block on the queue.
            self.get_event_loop().call_soon_threadsafe(
                self.create_task,
                self._sample_queue.put(None),
            )
            return
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
        """Process a text chunk for TTS synthesis."""
        _ = context_id
        try:
            await self.start_ttfb_metrics()
            await self.start_tts_usage_metrics(text)

            yield TTSStartedFrame()

            audio_buffer = b''
            first_chunk_for_ttfb = False

            async with self._reload_lock:
                # Reconcile the loaded model with the user's selection
                # *before* synthesizing — this is the single point where
                # a voice switch actually takes effect, guaranteeing the
                # utterance uses the requested voice (or the current one
                # if the new model isn't downloaded yet).
                await self._ensure_voice_loaded()

                if self._client is None:
                    # Piper is selected but no voice has been downloaded yet.
                    # End the turn quietly; the next utterance retries once the
                    # core process has fetched the model.
                    logger.warning(
                        'Piper selected but no voice downloaded yet; '
                        'skipping synthesis',
                        extra={'requested_voice_id': self._requested_voice_id},
                    )
                    yield TTSStoppedFrame()
                    return

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
