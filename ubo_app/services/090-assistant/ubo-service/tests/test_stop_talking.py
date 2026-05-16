"""Tests for the stop-talking event signal handler.

Verifies that ``StopTalkingOnSignal`` broadcasts an interruption on every
``AssistantStopTalkingEvent`` and stays inert otherwise.
"""

from __future__ import annotations

import unittest
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

from ubo_assistant.stop_talking import StopTalkingOnSignal


class _FakeClient:
    """Minimal client surface used by the StopTalking tests."""

    def __init__(self) -> None:
        """Capture the event callback and expose an event loop."""
        self.callback: Any = None
        self.unsubscribe = MagicMock()
        self.event_loop = MagicMock()
        self.event_loop.create_task = MagicMock(
            side_effect=self._record_coroutine,
        )

    def _record_coroutine(self, coro: Any) -> Any:  # noqa: ANN401
        """Close the coroutine to silence never-awaited warnings."""
        coro.close()
        return MagicMock()

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


def _build() -> tuple[StopTalkingOnSignal, _FakeClient]:
    client = _FakeClient()
    processor = StopTalkingOnSignal(client=cast('Any', client))
    return processor, client


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
