"""Stop-talking signal handler.

Subscribes to ``AssistantStopTalkingEvent`` and, on every emission,
broadcasts an ``InterruptionFrame`` so the in-flight LLM response and TTS
playback are cancelled. Unlike :class:`BargeInOnListenSignal` (which fires
on listening transitions to support barge-in), this processor reacts to an
explicit "okay enough" stop phrase: the user wants silence, not a new turn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from ubo_bindings.ubo.v1 import AssistantStopTalkingEvent, Event

if TYPE_CHECKING:
    from pipecat.frames.frames import Frame
    from ubo_bindings.client import UboRPCClient


class StopTalkingOnSignal(FrameProcessor):
    """Pass-through FrameProcessor that interrupts the bot on stop-talking.

    Lives in the pipeline so :meth:`broadcast_interruption` can propagate the
    interrupt both upstream and downstream. Frames flow through unchanged;
    the only side-effect is the event-driven broadcast on each
    ``AssistantStopTalkingEvent``.
    """

    def __init__(self, *, client: UboRPCClient) -> None:
        """Wire the processor to its UBO RPC client and event subscription."""
        super().__init__()
        self._client = client
        self._unsubscribe = client.subscribe_event(
            event_type=Event(
                assistant_stop_talking_event=AssistantStopTalkingEvent(),
            ),
            callback=self._on_stop_talking_event,
        )

    def _on_stop_talking_event(self, event: Event) -> None:
        """Schedule a bot interruption on every received stop-talking event."""
        _ = event
        logger.info(
            'AssistantStopTalkingEvent received; '
            'broadcasting InterruptionFrame to silence the assistant',
        )
        self._client.event_loop.create_task(self.broadcast_interruption())

    async def process_frame(
        self,
        frame: Frame,
        direction: FrameDirection,
    ) -> None:
        """Forward every frame unchanged."""
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

    async def cleanup(self) -> None:
        """Unsubscribe from the event subscription on teardown."""
        try:
            self._unsubscribe()
        except Exception:  # pragma: no cover - defensive
            logger.exception('Error unsubscribing StopTalkingOnSignal')
        await super().cleanup()
