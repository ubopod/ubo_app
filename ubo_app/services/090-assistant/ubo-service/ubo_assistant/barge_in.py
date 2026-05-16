"""Barge-in on ``AssistantStartListeningAction``.

Subscribes to ``state.assistant.is_listening`` and, on every ``False → True``
transition (e.g. when ubo-core dispatches ``AssistantStartListeningAction``
from a wake-phrase, keypad, or other trigger), broadcasts an
``InterruptionFrame`` so the in-flight LLM response and TTS playback are
cancelled and the user can interject mid-utterance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

if TYPE_CHECKING:
    from pipecat.frames.frames import Frame
    from ubo_bindings.client import UboRPCClient


class BargeInOnListenSignal(FrameProcessor):
    """Pass-through FrameProcessor that interrupts the bot when listen starts.

    Lives in the pipeline so :meth:`broadcast_interruption` can propagate the
    interrupt both upstream (input transport) and downstream (STT, LLM, TTS,
    output transport). Frames flow through unchanged; the only side-effect is
    the autorun-driven broadcast on a rising edge of ``is_listening``.
    """

    def __init__(self, *, client: UboRPCClient) -> None:
        """Wire the processor to its UBO RPC client."""
        super().__init__()
        self._client = client
        self._is_listening = False
        self._unsubscribe = client.autorun(['state.assistant.is_listening'])(
            self._on_listening_state_changed,
        )

    def _on_listening_state_changed(self, results: list) -> None:
        """Detect False → True transitions and schedule a bot interruption."""
        new_state = bool(results[0].value) if results else False
        was_listening = self._is_listening
        self._is_listening = new_state
        if not was_listening and new_state:
            logger.info(
                'AssistantStartListeningAction received; '
                'broadcasting InterruptionFrame to cancel in-flight bot output',
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
        """Unsubscribe from the autorun subscription on teardown."""
        try:
            self._unsubscribe()
        except Exception:  # pragma: no cover - defensive
            logger.exception('Error unsubscribing BargeInOnListenSignal')
        await super().cleanup()
