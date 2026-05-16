"""Tests for the barge-in on listen-start FrameProcessor.

Verifies that ``BargeInOnListenSignal`` broadcasts an interruption exactly on
every ``False → True`` transition of ``state.assistant.is_listening`` and
stays inert for every other transition.
"""

from __future__ import annotations

import asyncio
import unittest
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

from ubo_assistant.barge_in import BargeInOnListenSignal


class _Result:
    """Minimal stand-in for the autorun result objects exposing ``.value``."""

    def __init__(self, *, value: bool) -> None:
        """Store *value* as the underlying state field."""
        self.value = value


class _FakeClient:
    """Minimal client surface used by the BargeIn tests."""

    def __init__(self) -> None:
        """Capture the autorun callback and expose an event loop."""
        self.callback: Any = None
        self.unsubscribe = MagicMock()
        self.event_loop = MagicMock()
        self.event_loop.create_task = MagicMock(
            side_effect=self._record_coroutine,
        )
        self.scheduled_coroutines: list[Any] = []

    def _record_coroutine(self, coro: Any) -> Any:  # noqa: ANN401
        """Record and close the coroutine to avoid runtime warnings."""
        self.scheduled_coroutines.append(coro)
        # Close the coroutine so it doesn't warn about never being awaited.
        coro.close()
        return MagicMock()

    def autorun(self, selectors: list[str]) -> Any:  # noqa: ANN401
        """Return a registrar that captures the subscriber callback."""
        _ = selectors

        def register(callback: Any) -> Any:  # noqa: ANN401
            self.callback = callback
            return self.unsubscribe

        return register


def _build() -> tuple[BargeInOnListenSignal, _FakeClient]:
    client = _FakeClient()
    processor = BargeInOnListenSignal(client=cast('Any', client))
    return processor, client


class BargeInOnListenSignalTests(unittest.IsolatedAsyncioTestCase):
    """Behavioural tests for the barge-in processor."""

    async def test_initial_false_state_does_not_broadcast(self) -> None:
        """First callback with is_listening=False is a no-op baseline."""
        processor, client = _build()

        with patch.object(
            processor,
            'broadcast_interruption',
            new=AsyncMock(),
        ) as broadcast:
            client.callback([_Result(value=False)])
            await asyncio.sleep(0)

        broadcast.assert_not_called()
        client.event_loop.create_task.assert_not_called()

    async def test_false_to_true_schedules_broadcast(self) -> None:
        """Rising edge schedules a broadcast_interruption task."""
        processor, client = _build()

        with patch.object(
            processor,
            'broadcast_interruption',
            new=AsyncMock(),
        ):
            client.callback([_Result(value=False)])  # baseline
            client.callback([_Result(value=True)])  # rising edge

        self.assertEqual(  # noqa: PT009
            client.event_loop.create_task.call_count,
            1,
        )

    async def test_true_to_true_does_not_re_broadcast(self) -> None:
        """Repeated True with no fall in between does not re-trigger."""
        processor, client = _build()

        with patch.object(
            processor,
            'broadcast_interruption',
            new=AsyncMock(),
        ):
            client.callback([_Result(value=False)])  # baseline
            client.callback([_Result(value=True)])  # first rising edge
            client.callback([_Result(value=True)])  # no edge — stays True

        self.assertEqual(  # noqa: PT009
            client.event_loop.create_task.call_count,
            1,
        )

    async def test_true_to_false_does_not_broadcast(self) -> None:
        """Stop transition is silent — only rising edges interrupt."""
        processor, client = _build()

        with patch.object(
            processor,
            'broadcast_interruption',
            new=AsyncMock(),
        ):
            client.callback([_Result(value=False)])  # baseline
            client.callback([_Result(value=True)])  # rising edge → broadcast 1
            client.callback([_Result(value=False)])  # falling edge — silent
            client.callback([_Result(value=True)])  # rising edge → broadcast 2

        self.assertEqual(  # noqa: PT009
            client.event_loop.create_task.call_count,
            2,
        )

    async def test_cleanup_unsubscribes(self) -> None:
        """Cleanup invokes the unsubscribe callable returned by autorun."""
        processor, client = _build()

        with patch.object(
            BargeInOnListenSignal.__mro__[1],
            'cleanup',
            new=AsyncMock(),
        ):
            await processor.cleanup()

        client.unsubscribe.assert_called_once()


if __name__ == '__main__':
    unittest.main()
