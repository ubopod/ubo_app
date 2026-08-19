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

from ubo_assistant.constants import (
    MAX_AUDIO_CHUNK_BYTES,
    REQUEST_PIPELINE_SOURCE_ID,
)

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
        # Dispatch tasks, tracked so the end-marker can be ordered behind the
        # audio/text chunks.
        self._pending: list[asyncio.Task[object]] = []
        # Tail of the dispatch chain. ``UboRPCClient.dispatch`` returns straight
        # away after scheduling the RPC, so reporting chunks back-to-back put N
        # dispatches in flight at once and core received them in whatever order
        # they happened to land. That is audible: the ESP32 plays TTS chunks in
        # arrival order and does not sort by ``index`` (see the note in
        # ubo_lvgl/esp32/main/client_app.c), so speech came out reordered.
        # Chaining each dispatch behind its predecessor makes the order total
        # without blocking the pipeline that produces the frames.
        self._dispatch_chain: asyncio.Task[object] | None = None
        # Diagnostics: reports handed to the client vs dispatches that actually
        # completed. A gap means chunks never reached core.
        self.reports_dispatched = 0
        self.reports_failed = 0

    @property
    def sent_last_frame(self) -> bool:
        """Whether an end-of-stream marker has been dispatched."""
        return self._sent_last_frame

    def _report(self, data: AcceptableAssistanceFrame) -> None:
        previous = self._dispatch_chain

        async def send() -> None:
            if previous is not None:
                try:
                    await previous
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001, S110
                    # Ordering only -- a predecessor's failure is reported by
                    # _drain_pending, and must not stop this chunk being sent.
                    pass
            # Issued only now, so the RPC for chunk N+1 leaves after chunk N's
            # has completed and core sees them in emission order.
            task = self._client.dispatch(
                action=Action(
                    assistant_report_action=AssistantReportAction(
                        source_id=REQUEST_SOURCE_ID,
                        data=data,
                    ),
                ),
            )
            # Real client returns the dispatch task; the test fake returns None.
            if task is not None:
                await task
            self.reports_dispatched += 1

        chained = self._client.event_loop.create_task(send())
        self._dispatch_chain = chained
        # Tracked so the end-marker can wait for every chunk (ordering).
        self._pending.append(chained)

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
                self.reports_failed += 1
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
        # Split exactly as ``ubo_output_transport`` does: pipecat hands us ~0.5 s
        # frames (~48 KB at 48 kHz) and a client with ~50 KB of heap cannot
        # decode one, so the whole chunk is lost -- and on a still-image-sized
        # play buffer the ones that do decode overrun it. Whole-sample-aligned
        # so a 16-bit sample is never split across two chunks.
        align = _PCM_SAMPLE_WIDTH * max(frame.num_channels, 1)
        step = max(MAX_AUDIO_CHUNK_BYTES // align, 1) * align
        for offset in range(0, len(audio) or 1, step):
            self._report(
                AcceptableAssistanceFrame(
                    assistance_audio_frame=AssistanceAudioFrame(
                        audio=AudioSample(
                            data=audio[offset : offset + step],
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
            # Only end the stream once text has actually flowed — the same
            # guard the TTS branch below applies, and for a sharper reason.
            # pipecat pushes ``LLMFullResponseEndFrame`` from a ``finally``
            # (``openai/base_llm.py``), so a completion that failed outright
            # (402 out of credit, 401, 429, unreachable host) still ends with
            # one. Its ``push_error`` travels *upstream* to the task, while
            # this frame travels one hop *downstream* to us — so the end frame
            # wins the race, and marking the stream finished here would make
            # ``dispatch_error`` a no-op when the real error finally lands AND
            # suppress the request handler's "produced no output" backstop
            # (which requires ``not sent_last_frame``). The provider failure
            # then reaches the caller as an empty string with no error at all.
            # With no text yet, leave the stream open: a real error frame still
            # gets through, and a silent failure falls back to the timeout.
            elif isinstance(frame, LLMFullResponseEndFrame) and self.output_count > 0:
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
