"""Terminal pipeline collector that reports a request pipeline's output over gRPC."""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

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
    AudioPlayAudioSequenceAction,
    AudioSample,
    AudioSequenceSource,
)

from ubo_assistant.constants import REQUEST_PIPELINE_SOURCE_ID

if TYPE_CHECKING:
    from ubo_bindings.client import UboRPCClient

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
        # Set once the first output (or an error/last frame) is seen — used by the
        # request handler to know when a streaming STT has produced its transcription.
        self.first_output: asyncio.Event = asyncio.Event()

    @property
    def sent_last_frame(self) -> bool:
        """Whether an end-of-stream marker has been dispatched."""
        return self._sent_last_frame

    def _report(self, data: AcceptableAssistanceFrame) -> None:
        self._client.dispatch(
            action=Action(
                assistant_report_action=AssistantReportAction(
                    source_id=REQUEST_SOURCE_ID,
                    data=data,
                ),
            ),
        )

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

    def _dispatch_audio(self, frame: TTSAudioRawFrame) -> None:
        self._report(
            AcceptableAssistanceFrame(
                assistance_audio_frame=AssistanceAudioFrame(
                    audio=AudioSample(
                        data=frame.audio,
                        rate=frame.sample_rate,
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

    def dispatch_error(self, error: str) -> None:
        """Dispatch an error frame and mark the stream finished (once only)."""
        if self._sent_last_frame:
            return
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

    def dispatch_last_frame(self) -> None:
        """Dispatch end-of-stream sentinel(s); idempotent.

        For TTS terminals, *also* dispatches a sentinel
        ``AudioPlayAudioSequenceAction(sample=None, ...)`` directly (not
        wrapped in an ``AssistanceAudioFrame``). The audio manager breaks
        out of its play loop on ``sample is None`` instead of waiting
        for the 1 s empty-buffer fallback. Direct dispatch sidesteps the
        wire-level oneof handling for ``AssistanceAudioFrame(audio=None)``
        which can be dropped because the inner message has no
        distinguishing non-default content.
        """
        if self._sent_last_frame:
            return
        if self._terminal_stage is AssistantPipelineStage.TTS:
            # ``_index`` here equals the count of audio chunks already
            # dispatched, so it lands at the next slot after the final
            # audio frame — exactly where the audio service's play loop
            # head sits. Direct dispatch (skipping the ``_report`` /
            # ``AssistantReportAction`` wrapper) avoids the wire-level
            # oneof handling for an empty inner ``AssistanceAudioFrame``.
            self._client.dispatch(
                action=Action(
                    audio_play_audio_sequence_action=AudioPlayAudioSequenceAction(
                        sample=None,
                        id=f'assistant:{REQUEST_SOURCE_ID}:{self._assistance_id}',
                        index=self._index,
                        source=AudioSequenceSource.OTHER,
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
        self._index += 1
        self._sent_last_frame = True
        self.first_output.set()

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Tap the terminal stage's output frames and report them over gRPC."""
        await super().process_frame(frame, direction)

        if self._terminal_stage is AssistantPipelineStage.STT:
            if isinstance(frame, TranscriptionFrame):
                self._dispatch_text(frame.text)
        elif self._terminal_stage is AssistantPipelineStage.LLM:
            if isinstance(frame, LLMTextFrame):
                self._dispatch_text(frame.text)
            elif isinstance(frame, LLMFullResponseEndFrame):
                self.dispatch_last_frame()
        elif self._terminal_stage is AssistantPipelineStage.TTS:
            if isinstance(frame, TTSAudioRawFrame) and frame.audio:
                self._dispatch_audio(frame)
            elif isinstance(frame, TTSStoppedFrame):
                self.dispatch_last_frame()

        await self.push_frame(frame, direction)
