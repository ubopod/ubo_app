"""Tests for the stop-talking event signal handler.

Verifies that ``StopTalkingOnSignal`` broadcasts an interruption on every
``AssistantStopTalkingEvent``, discards the pending user turn so it never
reaches the LLM, and stays inert otherwise.
"""

from __future__ import annotations

import unittest
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

from pipecat.frames.frames import (
    InterimTranscriptionFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from ubo_assistant.stop_talking import StopTalkingOnSignal


class _FakeClient:
    """Minimal client surface used by the StopTalking tests."""

    def __init__(self) -> None:
        """Capture the event callback and expose an event loop."""
        self.callback: Any = None
        self.unsubscribe = MagicMock()
        self.scheduled: list[Any] = []
        self.event_loop = MagicMock()
        self.event_loop.create_task = MagicMock(
            side_effect=self._record_coroutine,
        )

    def _record_coroutine(self, coro: Any) -> Any:  # noqa: ANN401
        """Keep the coroutine so a test can await it, or close it if unused."""
        self.scheduled.append(coro)
        return MagicMock()

    def close_scheduled(self) -> None:
        """Close any coroutine a test never awaited (silences warnings)."""
        for coro in self.scheduled:
            coro.close()
        self.scheduled.clear()

    def subscribe_event(
        self,
        *,
        event_type: Any,  # noqa: ANN401
        callback: Any,  # noqa: ANN401
    ) -> Any:  # noqa: ANN401
        """Capture the callback and return an unsubscribe mock."""
        _ = event_type
        self.callback = callback
        return self.unsubscribe


def _transcription(text: str) -> TranscriptionFrame:
    return TranscriptionFrame(text=text, user_id='user', timestamp='0')


def _build(
    user_aggregator: Any = None,  # noqa: ANN401
) -> tuple[StopTalkingOnSignal, _FakeClient]:
    client = _FakeClient()
    processor = StopTalkingOnSignal(
        client=cast('Any', client),
        user_aggregator=user_aggregator,
    )
    return processor, client


async def _process(processor: StopTalkingOnSignal, frame: Any) -> list[Any]:  # noqa: ANN401
    """Run one frame through ``process_frame``, returning what was pushed on.

    Stubs out the ``FrameProcessor`` base so the processor can be exercised
    without a running pipeline.
    """
    pushed: list[Any] = []
    with (
        patch.object(
            StopTalkingOnSignal.__mro__[1],
            'process_frame',
            new=AsyncMock(),
        ),
        patch.object(
            processor,
            'push_frame',
            new=AsyncMock(side_effect=lambda frame, _direction: pushed.append(frame)),
        ),
    ):
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)
    return pushed


class StopTalkingOnSignalTests(unittest.IsolatedAsyncioTestCase):
    """Behavioural tests for the stop-talking processor."""

    async def test_event_schedules_broadcast_interruption(self) -> None:
        """Each received event schedules a broadcast_interruption task."""
        processor, client = _build()

        with patch.object(
            processor,
            'broadcast_interruption',
            new=AsyncMock(),
        ):
            client.callback(MagicMock())

        self.assertEqual(  # noqa: PT009
            client.event_loop.create_task.call_count,
            1,
        )
        client.close_scheduled()

    async def test_multiple_events_schedule_multiple_broadcasts(self) -> None:
        """Repeated events trigger one broadcast each."""
        processor, client = _build()

        with patch.object(
            processor,
            'broadcast_interruption',
            new=AsyncMock(),
        ):
            client.callback(MagicMock())
            client.callback(MagicMock())
            client.callback(MagicMock())

        self.assertEqual(  # noqa: PT009
            client.event_loop.create_task.call_count,
            3,
        )
        client.close_scheduled()

    async def test_event_resets_the_pending_user_aggregation(self) -> None:
        """The scheduled task clears whatever the user aggregator already holds.

        A transcript that landed before the stop signal is sitting in the
        aggregator's ``_aggregation``; pipecat's ``InterruptionFrame`` does not
        touch it, and session teardown would flush it to the LLM.
        """
        aggregator = MagicMock()
        aggregator.reset = AsyncMock()
        processor, client = _build(user_aggregator=aggregator)

        with patch.object(
            processor,
            'broadcast_interruption',
            new=AsyncMock(),
        ):
            client.callback(MagicMock())
            for coro in client.scheduled:
                await coro
            client.scheduled.clear()

        aggregator.reset.assert_awaited_once()

    async def test_transcription_after_stop_is_not_forwarded(self) -> None:
        """A late STT final arriving after the stop signal never reaches the LLM.

        Vosk matches the command locally well before the cloud STT finalizes, so
        the final ``TranscriptionFrame`` lands *after* the interruption. Nothing
        upstream drops it, so this processor must.
        """
        processor, client = _build()

        with patch.object(
            processor,
            'broadcast_interruption',
            new=AsyncMock(),
        ):
            client.callback(MagicMock())
        client.close_scheduled()

        pushed = await _process(processor, _transcription('turn on the lights'))

        self.assertEqual(pushed, [])  # noqa: PT009

    async def test_interim_transcription_after_stop_is_not_forwarded(self) -> None:
        """Interim transcripts are dropped too, so end-of-turn cannot re-fire."""
        processor, client = _build()

        with patch.object(
            processor,
            'broadcast_interruption',
            new=AsyncMock(),
        ):
            client.callback(MagicMock())
        client.close_scheduled()

        frame = InterimTranscriptionFrame(
            text='turn on',
            user_id='user',
            timestamp='0',
        )
        pushed = await _process(processor, frame)

        self.assertEqual(pushed, [])  # noqa: PT009

    async def test_transcription_is_forwarded_when_not_discarding(self) -> None:
        """Without a stop signal the processor stays a pass-through."""
        processor, _client = _build()

        frame = _transcription('what is the weather')
        pushed = await _process(processor, frame)

        self.assertEqual(pushed, [frame])  # noqa: PT009

    async def test_next_user_turn_rearms_the_processor(self) -> None:
        """Discarding is scoped to the stopped turn, not the rest of the session."""
        processor, client = _build()

        with patch.object(
            processor,
            'broadcast_interruption',
            new=AsyncMock(),
        ):
            client.callback(MagicMock())
        client.close_scheduled()

        await _process(processor, UserStartedSpeakingFrame())
        frame = _transcription('what is the weather')
        pushed = await _process(processor, frame)

        self.assertEqual(pushed, [frame])  # noqa: PT009

    async def test_cleanup_unsubscribes(self) -> None:
        """Cleanup invokes the unsubscribe callable returned by subscribe_event."""
        processor, client = _build()

        with patch.object(
            StopTalkingOnSignal.__mro__[1],
            'cleanup',
            new=AsyncMock(),
        ):
            await processor.cleanup()

        client.unsubscribe.assert_called_once()


if __name__ == '__main__':
    unittest.main()
