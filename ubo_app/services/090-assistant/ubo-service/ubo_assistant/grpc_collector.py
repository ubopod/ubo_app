"""Terminal pipeline collector that reports a request pipeline's output over gRPC."""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

from loguru import logger
from pipecat.audio.utils import create_stream_resampler
from pipecat.frames.frames import (
    Frame,
    LLMFullResponseEndFrame,
    LLMTextFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSStoppedFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from ubo_bindings.ubo.v1 import (
    AcceptableAssistanceFrame,
    Action,
    AssistanceAudioFrame,
    AssistanceErrorFrame,
    AssistanceTextFrame,
    AssistantPipelineStage,
    AssistantReportAction,
    AudioSample,
)

from ubo_assistant.constants import REQUEST_PIPELINE_SOURCE_ID

if TYPE_CHECKING:
    from pipecat.audio.resamplers.base_audio_resampler import BaseAudioResampler
    from ubo_bindings.client import UboRPCClient

# The device's audio hardware runs at 48 kHz. The live pipeline's output
# transport (``ubo_output_transport.py``) resamples every TTS frame to this
# rate before playback; the one-shot path must do the same, otherwise the
# raw provider rate is dispatched and the audio service's implicit handling
# silently drops some streams (e.g. Venice) while passing others (OpenAI).
_UBO_TARGET_SAMPLE_RATE = 48000

# Re-exported under the historical name kept by external consumers (tests,
# the request handler). The canonical definition lives in
# ``ubo_assistant/constants.py`` and mirrors
# ``ubo_app.store.services.assistant.REQUEST_PIPELINE_SOURCE_ID``.
REQUEST_SOURCE_ID = REQUEST_PIPELINE_SOURCE_ID

_PCM_SAMPLE_WIDTH = 2


class GRPCTerminalCollector(FrameProcessor):
    """Terminal processor that taps the last stage's output and reports it over gRPC.

    Placed at the end of a request pipeline. Depending on ``terminal_stage`` it taps
    transcription / LLM text / TTS audio frames and dispatches the matching
    ``Assistance*Frame`` back to core. ``dispatch_last_frame`` is sent exactly once.
    """

    def __init__(
        self,
        *,
        client: UboRPCClient,
        session_id: str,
        terminal_stage: AssistantPipelineStage,
    ) -> None:
        """Initialize the collector for the given session and terminal stage."""
        super().__init__()
        self._client = client
        self._session_id = session_id
        self._terminal_stage = terminal_stage
        self._assistance_id = uuid.uuid4().hex
        self._index = 0
        self._sent_last_frame = False
        self.output_count = 0
        # Diagnostics: total audio bytes dispatched and the last sample rate seen,
        # so the request handler can report whether a TTS provider produced real
        # audio (and at what rate) vs an empty/garbled stream.
        self.audio_bytes = 0
        self.audio_rate = 0
        # Per-input-rate resamplers used to normalize TTS audio to the device
        # rate before dispatch (mirrors ubo_output_transport).
        self._resamplers: dict[int, BaseAudioResampler] = {}
        # Per-rate carry of a trailing partial int16 sample. The soxr resampler
        # reads the bytes as int16, so an odd-length chunk — a sample split across
        # two websocket frames, as Rime occasionally emits — would raise "buffer
        # size must be a multiple of element size". We resample only whole samples
        # and carry the leftover byte(s) into the next chunk.
        self._resample_remainder: dict[int, bytes] = {}
        # Set once the first output (or an error/last frame) is seen — used by the
        # request handler to know when a streaming STT has produced its transcription.
        self.first_output: asyncio.Event = asyncio.Event()
        # Set once the terminal stage signals end-of-stream (last frame) or an
        # error — lets the request handler finish promptly instead of waiting on a
        # lingering run task (e.g. websocket TTS that idles after delivering audio).
        self.last_output: asyncio.Event = asyncio.Event()
        # Set once a *finalized* STT transcript is seen (Deepgram's from_finalize
        # response, or any SegmentedSTTService frame) — the deterministic signal
        # that a streaming STT has emitted its complete transcript.
        self.stt_finalized: asyncio.Event = asyncio.Event()
        # Fire-and-forget dispatch tasks, tracked so the end-marker can be ordered
        # behind the audio/text chunks (the real client dispatches concurrently).
        self._pending: list[asyncio.Task[object]] = []

    @property
    def sent_last_frame(self) -> bool:
        """Whether an end-of-stream marker has been dispatched."""
        return self._sent_last_frame

    def _report(self, data: AcceptableAssistanceFrame) -> None:
        task = self._client.dispatch(
            action=Action(
                assistant_report_action=AssistantReportAction(
                    source_id=REQUEST_SOURCE_ID,
                    data=data,
                ),
            ),
        )
        # Real client returns the fire-and-forget task; the test fake returns
        # None. Track it so the end-marker can wait for it (ordering).
        if task is not None:
            self._pending.append(task)

    async def _drain_pending(self) -> None:
        """Wait for in-flight dispatches so the next one is ordered behind them."""
        if not self._pending:
            return
        pending = self._pending
        self._pending = []
        results = await asyncio.gather(*pending, return_exceptions=True)
        # Surface (don't silently swallow) a failed dispatch; CancelledError is a
        # BaseException, so ``Exception`` skips ordinary task cancellation.
        for result in results:
            if isinstance(result, Exception):
                message = f'screen-reader: a report dispatch failed: {result!r}'
                logger.warning(message)

    def _dispatch_text(self, text: str) -> None:
        self._report(
            AcceptableAssistanceFrame(
                assistance_text_frame=AssistanceTextFrame(
                    text=text,
                    timestamp=self._client.event_loop.time(),
                    id=self._assistance_id,
                    index=self._index,
                    source=self._terminal_stage,
                    session_id=self._session_id,
                ),
            ),
        )
        self._index += 1
        self.output_count += 1
        self.first_output.set()

    async def _dispatch_audio(self, frame: TTSAudioRawFrame) -> None:
        audio = frame.audio
        rate = frame.sample_rate
        if rate != _UBO_TARGET_SAMPLE_RATE:
            resampler = self._resamplers.get(rate)
            if resampler is None:
                resampler = create_stream_resampler()
                self._resamplers[rate] = resampler
            # Resample only whole int16 samples; carry any trailing partial sample
            # (odd byte) into the next chunk so soxr never sees a misaligned buffer.
            buffer = self._resample_remainder.get(rate, b'') + audio
            aligned = len(buffer) - len(buffer) % _PCM_SAMPLE_WIDTH
            self._resample_remainder[rate] = buffer[aligned:]
            if aligned == 0:
                # Nothing but a carried partial sample so far — wait for the rest.
                return
            audio = await resampler.resample(
                buffer[:aligned],
                rate,
                _UBO_TARGET_SAMPLE_RATE,
            )
            rate = _UBO_TARGET_SAMPLE_RATE
        self.audio_bytes += len(audio)
        self.audio_rate = rate
        self._report(
            AcceptableAssistanceFrame(
                assistance_audio_frame=AssistanceAudioFrame(
                    audio=AudioSample(
                        data=audio,
                        rate=rate,
                        channels=frame.num_channels,
                        width=_PCM_SAMPLE_WIDTH,
                    ),
                    timestamp=self._client.event_loop.time(),
                    id=self._assistance_id,
                    index=self._index,
                    session_id=self._session_id,
                ),
            ),
        )
        self._index += 1
        self.output_count += 1
        self.first_output.set()

    async def dispatch_error(self, error: str) -> None:
        """Dispatch a terminal error frame and mark the stream finished (once).

        Drains prior dispatches first (same ordering barrier as
        ``dispatch_last_frame``) so the terminal ``is_last_frame`` error can't
        overtake earlier in-flight audio/text reports when a provider emits some
        output and then raises.
        """
        if self._sent_last_frame:
            return
        await self._drain_pending()
        self._report(
            AcceptableAssistanceFrame(
                assistance_error_frame=AssistanceErrorFrame(
                    error=error,
                    timestamp=self._client.event_loop.time(),
                    id=self._assistance_id,
                    index=self._index,
                    session_id=self._session_id,
                    is_last_frame=True,
                ),
            ),
        )
        self._sent_last_frame = True
        self.first_output.set()
        self.last_output.set()

    async def dispatch_last_frame(self) -> None:
        """Dispatch the end-of-stream marker(s); idempotent.

        For TTS terminals this emits an ``AssistanceAudioFrame(audio=None,
        is_last_frame=True)``. Core-side, ``_communicate`` turns it into the
        ``AudioPlayAudioSequenceAction(sample=None)`` that breaks the audio
        manager's play loop immediately (instead of waiting out the 1 s
        empty-buffer fallback). ``is_last_frame=True`` is non-default content, so
        the inner frame survives the wire-level oneof handling.

        It is sent through the SAME report path as the audio chunks (not as a
        direct ``AudioPlayAudioSequenceAction``) and only after prior dispatches
        have reached the server, so the marker can't race ahead of the still
        in-flight audio chunks and end the sequence early.
        """
        if self._sent_last_frame:
            return
        # Order the marker behind every audio/text chunk already dispatched.
        await self._drain_pending()
        if self._terminal_stage is AssistantPipelineStage.TTS:
            # ``_index`` equals the count of audio chunks dispatched, so the
            # marker lands at the next slot — where the play-loop head sits.
            self._report(
                AcceptableAssistanceFrame(
                    assistance_audio_frame=AssistanceAudioFrame(
                        audio=None,
                        is_last_frame=True,
                        timestamp=self._client.event_loop.time(),
                        id=self._assistance_id,
                        index=self._index,
                        session_id=self._session_id,
                    ),
                ),
            )
        self._report(
            AcceptableAssistanceFrame(
                assistance_text_frame=AssistanceTextFrame(
                    text='',
                    timestamp=self._client.event_loop.time(),
                    id=self._assistance_id,
                    index=self._index,
                    source=self._terminal_stage,
                    session_id=self._session_id,
                    is_last_frame=True,
                ),
            ),
        )
        # These terminal report dispatches are intentionally NOT drained: nothing
        # downstream waits on them, ordering behind the chunks is already
        # guaranteed by the drain above, and the long-lived client loop delivers
        # them after this returns. (Draining here would only serialize teardown.)
        self._index += 1
        self._sent_last_frame = True
        self.first_output.set()
        self.last_output.set()

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Tap the terminal stage's output frames and report them over gRPC."""
        await super().process_frame(frame, direction)

        if self._terminal_stage is AssistantPipelineStage.STT:
            if isinstance(frame, TranscriptionFrame):
                self._dispatch_text(frame.text)
                if getattr(frame, 'finalized', False):
                    self.stt_finalized.set()
        elif self._terminal_stage is AssistantPipelineStage.LLM:
            if isinstance(frame, LLMTextFrame):
                self._dispatch_text(frame.text)
            elif isinstance(frame, LLMFullResponseEndFrame):
                await self.dispatch_last_frame()
        elif self._terminal_stage is AssistantPipelineStage.TTS:
            if isinstance(frame, TTSAudioRawFrame) and frame.audio:
                await self._dispatch_audio(frame)
            # Only end the stream once real audio has actually flowed. A
            # TTSStoppedFrame can arrive BEFORE the first audio frame when a
            # provider is slow to start streaming — e.g. Venice's cold-connection
            # time-to-first-byte (~4s: TLS + model warmup) exceeds the time the
            # stopped frame takes to reach us. Ending now would dispatch the
            # is_last_frame marker that breaks the core's audio play loop, so the
            # audio arriving a moment later is silently dropped (heard as "no
            # audio"; the 0-byte case is the same race with a wider margin). With
            # no audio yet, ignore this stopped frame and let the run finish
            # naturally — the request handler already races run-task completion,
            # and the trailing dispatch_last_frame() then lands AFTER the audio.
            elif isinstance(frame, TTSStoppedFrame) and self.output_count > 0:
                await self.dispatch_last_frame()

        await self.push_frame(frame, direction)
