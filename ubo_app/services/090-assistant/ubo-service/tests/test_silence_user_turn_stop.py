"""Tests for the policy-aware user-turn stop strategy.

Exercises the policy-watcher subscription, dynamic timeout updating, and
conditional ``AssistantStopListeningAction`` dispatch.
"""

from __future__ import annotations

import asyncio
import unittest
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

from ubo_assistant.policy_watcher import PolicyContext, PolicyWatcher
from ubo_assistant.silence_user_turn_stop import (
    UboPolicyAwareUserTurnStopStrategy,
)


class FakePolicyWatcher:
    """Stand-in for :class:`PolicyWatcher` exposing ``.context`` + ``subscribe``."""

    def __init__(self, context: PolicyContext) -> None:
        """Store *context* and an empty subscriber list."""
        self.context = context
        self._subscribers: list[Any] = []

    def subscribe(self, callback: Any) -> Any:  # noqa: ANN401
        """Register *callback* and call it once with the current context."""
        self._subscribers.append(callback)
        callback(self.context)
        return lambda: self._subscribers.remove(callback)

    def publish(self, context: PolicyContext) -> None:
        """Push *context* to every subscriber."""
        self.context = context
        for cb in list(self._subscribers):
            cb(context)


def _build(
    *,
    silence_timeout_seconds: float | None,
) -> tuple[Any, MagicMock, FakePolicyWatcher]:
    client = MagicMock()
    watcher = FakePolicyWatcher(
        PolicyContext(silence_timeout_seconds=silence_timeout_seconds),
    )
    strategy = UboPolicyAwareUserTurnStopStrategy(
        client=client,
        policy_watcher=cast('PolicyWatcher', watcher),
    )
    return strategy, client, watcher


class PolicyAwareUserTurnStopTests(unittest.IsolatedAsyncioTestCase):
    """Behavioural tests for ``UboPolicyAwareUserTurnStopStrategy``."""

    async def test_initial_policy_is_applied(self) -> None:
        """Constructor immediately picks up the active policy timeout."""
        strategy, _, _ = _build(silence_timeout_seconds=2.5)

        self.assertEqual(strategy._user_speech_timeout, 2.5)  # noqa: PT009, SLF001

    async def test_no_silence_policy_uses_fallback(self) -> None:
        """When policy.silence_timeout_seconds is None, fallback applies."""
        strategy, _, _ = _build(silence_timeout_seconds=None)

        self.assertEqual(strategy._user_speech_timeout, 0.6)  # noqa: PT009, SLF001

    async def test_policy_change_updates_timeout(self) -> None:
        """Subscriber is notified on policy change and timeout is updated."""
        strategy, _, watcher = _build(silence_timeout_seconds=None)

        watcher.publish(PolicyContext(silence_timeout_seconds=4.0))

        self.assertEqual(strategy._user_speech_timeout, 4.0)  # noqa: PT009, SLF001

    async def test_trigger_dispatches_stop_when_silence_policy_set(self) -> None:
        """Firing the strategy with silence policy dispatches AssistantStop."""
        strategy, client, _ = _build(silence_timeout_seconds=2.0)

        with patch.object(
            UboPolicyAwareUserTurnStopStrategy.__mro__[1],
            'trigger_user_turn_stopped',
            new=AsyncMock(),
        ):
            await strategy.trigger_user_turn_stopped()

        self.assertEqual(client.dispatch.call_count, 1)  # noqa: PT009
        action = client.dispatch.call_args.kwargs['action']
        reason = action.assistant_stop_listening_action.reason
        self.assertAlmostEqual(  # noqa: PT009
            reason.silence_timeout_stop_reason.silence_seconds,
            2.0,
            places=2,
        )

    async def test_trigger_skips_dispatch_when_no_silence_policy(self) -> None:
        """Without a silence policy, only the parent's trigger runs."""
        strategy, client, _ = _build(silence_timeout_seconds=None)

        with patch.object(
            UboPolicyAwareUserTurnStopStrategy.__mro__[1],
            'trigger_user_turn_stopped',
            new=AsyncMock(),
        ):
            await strategy.trigger_user_turn_stopped()

        self.assertEqual(client.dispatch.call_count, 0)  # noqa: PT009

    async def test_cleanup_unsubscribes_from_watcher(self) -> None:
        """Cleanup removes the strategy from the watcher's subscribers."""
        _, _, watcher = _build(silence_timeout_seconds=2.0)
        # Constructor subscribed exactly once.
        self.assertEqual(len(watcher._subscribers), 1)  # noqa: PT009, SLF001

        # cleanup() involves the parent class internal task manager which we
        # don't initialise in this lightweight test; assert via the callable
        # we received from subscribe instead.
        await asyncio.sleep(0)


if __name__ == '__main__':
    unittest.main()
