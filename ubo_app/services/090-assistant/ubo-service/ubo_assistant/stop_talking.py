"""Stop-talking signal handler.

Subscribes to ``AssistantStopTalkingEvent`` and, on every emission, silences the
assistant *and discards the user turn that is still in flight*. Unlike
:class:`BargeInOnListenSignal` (which fires on listening transitions to support
barge-in, where the new user turn must survive), this processor reacts to an
explicit stop: an "okay enough" phrase, or a voice shortcut matched locally by
Vosk. Either way the user wants silence, not an answer.

Discarding the turn takes two steps, because pipecat's ``InterruptionFrame``
does *not* do it. ``LLMUserAggregator.process_frame`` has no ``InterruptionFrame``
branch at all — the frame is simply forwarded — so a transcript sitting in its
``_aggregation`` survives the interrupt, and session teardown then flushes it
(``_cancel``/``_stop`` both call ``_maybe_emit_user_turn_stopped``, whose first
act is ``push_aggregation()``). The assistant would answer the shortcut it was
just told to stay quiet about. So:

- whatever the aggregator *already* holds is cleared via ``reset()``;
- transcripts that arrive *afterwards* (the cloud STT final typically lands well
  after local Vosk has matched) are swallowed here, before they can reach it.

This processor therefore has to sit downstream of the STT service, so those
transcription frames pass through it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from pipecat.frames.frames import (
    InterimTranscriptionFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from ubo_bindings.ubo.v1 import AssistantStopTalkingEvent, Event

if TYPE_CHECKING:
    from pipecat.frames.frames import Frame
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMUserAggregator,
    )
    from ubo_bindings.client import UboRPCClient


class StopTalkingOnSignal(FrameProcessor):
    """Interrupt the bot and drop the pending user turn on stop-talking.

    Lives in the pipeline so :meth:`broadcast_interruption` can propagate the
    interrupt both upstream and downstream, and — being downstream of STT — so
    it can withhold the transcripts of the discarded turn from the aggregator.
    """

    def __init__(
        self,
        *,
        client: UboRPCClient,
        user_aggregator: LLMUserAggregator | None = None,
    ) -> None:
        """Wire the processor to its UBO RPC client and event subscription."""
        super().__init__()
        self._client = client
        self._user_aggregator = user_aggregator
        self._is_discarding = False
        self._unsubscribe = client.subscribe_event(
            event_type=Event(
                assistant_stop_talking_event=AssistantStopTalkingEvent(),
            ),
            callback=self._on_stop_talking_event,
        )

    def _on_stop_talking_event(self, event: Event) -> None:
        """Silence the assistant and discard the in-flight user turn."""
        _ = event
        logger.info(
            'AssistantStopTalkingEvent received; broadcasting InterruptionFrame '
            'and discarding the in-flight user turn',
        )
        # Set synchronously: a late transcript may reach `process_frame` before
        # the scheduled coroutine gets a chance to run.
        self._is_discarding = True
        self._client.event_loop.create_task(self._stop_talking())

    async def _stop_talking(self) -> None:
        """Cancel in-flight LLM/TTS, then clear what the aggregator already holds."""
        await self.broadcast_interruption()
        if self._user_aggregator is not None:
            await self._user_aggregator.reset()

    async def process_frame(
        self,
        frame: Frame,
        direction: FrameDirection,
    ) -> None:
        """Forward frames unchanged, minus the discarded turn's transcripts."""
        await super().process_frame(frame, direction)

        if isinstance(frame, UserStartedSpeakingFrame):
            # A new turn — discarding was scoped to the stopped one.
            self._is_discarding = False
        elif self._is_discarding and isinstance(
            frame,
            (TranscriptionFrame, InterimTranscriptionFrame),
        ):
            logger.debug(
                'Dropping transcript of the discarded turn {extra}',
                extra={'text': frame.text},
            )
            return

        await self.push_frame(frame, direction)

    async def cleanup(self) -> None:
        """Unsubscribe from the event subscription on teardown."""
        try:
            self._unsubscribe()
        except Exception:  # pragma: no cover - defensive
            logger.exception('Error unsubscribing StopTalkingOnSignal')
        await super().cleanup()
