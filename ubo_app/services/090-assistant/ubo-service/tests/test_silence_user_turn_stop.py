"""Tests for the policy-aware user-turn stop strategy.

Exercises silence-policy completion/dispatch, manual (push-to-talk) suppression
while listening, and the release-edge flush that sends a held turn to the LLM.
"""

from __future__ import annotations

import asyncio
import unittest
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

from pipecat.frames.frames import InterruptionFrame
from pipecat.turns.types import ProcessFrameResult
from ubo_bindings.ubo.v1 import AssistantTriggerPolicy, AssistantTurnCompletionMode

import ubo_assistant.silence_user_turn_stop as module
from ubo_assistant.policy_watcher import PolicyContext, PolicyWatcher
from ubo_assistant.silence_user_turn_stop import UboPolicyAwareUserTurnStopStrategy

_PARENT = UboPolicyAwareUserTurnStopStrategy.__mro__[1]


class _Result:
    """Minimal stand-in for autorun result objects exposing ``.value``."""

    def __init__(self, value: object) -> None:
        """Store *value* as the underlying state field."""
        self.value = value


class _FakeClient:
    """Minimal client surface: autorun capture, dispatch, event loop."""

    def __init__(self) -> None:
        """Initialise capture slots, dispatch mock and a placeholder loop."""
        self.listening_callback: Any = None
        self.dispatch = MagicMock()
        self.unsubscribe = MagicMock()
        self.event_loop: Any = MagicMock()

    def autorun(self, selectors: list[str]) -> Any:  # noqa: ANN401
        """Return a registrar that captures the subscriber callback."""
        _ = selectors

        def register(callback: Any) -> Any:  # noqa: ANN401
            self.listening_callback = callback
            return self.unsubscribe

        return register


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


def _policy_msg(*, manual: bool) -> AssistantTriggerPolicy:
    """Build the active-policy message exactly as the autorun delivers it.

    Round-tripped through ``FromString`` so the test exercises the real wire
    representation (the autorun hands the strategy the unwrapped
    ``AssistantTriggerPolicy`` message itself — not a ``.value`` wrapper).
    """
    mode = (
        AssistantTurnCompletionMode.MANUAL
        if manual
        else AssistantTurnCompletionMode.SILENCE
    )
    return AssistantTriggerPolicy.FromString(
        bytes(AssistantTriggerPolicy(completion_mode=mode)),
    )


def _build(
    *,
    silence_timeout_seconds: float | None = None,
    completion_mode: str = 'silence',
    end_of_turn_phrases: tuple[str, ...] = (),
) -> tuple[Any, _FakeClient, FakePolicyWatcher]:
    """Construct a strategy wired to fake client + policy watcher."""
    client = _FakeClient()
    watcher = FakePolicyWatcher(
        PolicyContext(
            silence_timeout_seconds=silence_timeout_seconds,
            completion_mode=completion_mode,
            end_of_turn_phrases=end_of_turn_phrases,
        ),
    )
    strategy = UboPolicyAwareUserTurnStopStrategy(
        client=cast('Any', client),
        policy_watcher=cast('PolicyWatcher', watcher),
    )
    return strategy, client, watcher


def _start_session(client: _FakeClient, *, manual: bool) -> None:
    """Drive the listening autorun rising edge with the given policy mode.

    Mirrors the real autorun payload: the ``is_listening`` slot is a scalar
    wrapper, the ``active_policy`` slot is the raw policy message.
    """
    client.listening_callback([_Result(value=True), _policy_msg(manual=manual)])


def _end_session(client: _FakeClient) -> None:
    """Drive the listening autorun falling edge (session ended, policy None)."""
    client.listening_callback([_Result(value=False), None])


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

    async def test_silence_trigger_dispatches_stop(self) -> None:
        """Silence policy: trigger fires parent and dispatches the stop action."""
        strategy, client, _ = _build(silence_timeout_seconds=2.0)
        with patch.object(_PARENT, 'trigger_user_turn_stopped', new=AsyncMock()):
            await strategy.trigger_user_turn_stopped()
        self.assertEqual(client.dispatch.call_count, 1)  # noqa: PT009
        action = client.dispatch.call_args.kwargs['action']
        reason = action.assistant_stop_listening_action.reason
        self.assertAlmostEqual(  # noqa: PT009
            reason.silence_timeout_stop_reason.silence_seconds,
            2.0,
            places=2,
        )

    async def test_manual_session_latched_from_real_policy_message(self) -> None:
        """The MANUAL (IR/keypad) policy is recognised from the wire payload.

        Regression: the autorun delivers ``active_policy`` as the raw
        ``AssistantTriggerPolicy`` message (no ``.value`` wrapper). Reading it
        wrong left ``_session_is_manual`` False, so a mid-hold pause flushed the
        turn to the LLM before the user toggled listening off.
        """
        strategy, client, _ = _build(completion_mode='manual')
        _start_session(client, manual=True)
        self.assertTrue(strategy._session_is_manual)  # noqa: PT009, SLF001

    async def test_silence_session_not_latched_manual(self) -> None:
        """A silence policy session is not treated as push-to-talk."""
        strategy, client, _ = _build(silence_timeout_seconds=2.0)
        _start_session(client, manual=False)
        self.assertFalse(strategy._session_is_manual)  # noqa: PT009, SLF001

    async def test_manual_session_suppresses_silence_trigger(self) -> None:
        """While a held PTT session is listening, silence never completes."""
        strategy, client, _ = _build(completion_mode='manual')
        _start_session(client, manual=True)

        parent = AsyncMock()
        with patch.object(_PARENT, 'trigger_user_turn_stopped', new=parent):
            await strategy.trigger_user_turn_stopped()

        self.assertEqual(parent.await_count, 0)  # noqa: PT009
        self.assertEqual(client.dispatch.call_count, 0)  # noqa: PT009

    async def test_manual_release_flushes_after_settle(self) -> None:
        """Releasing a PTT session flushes the accumulated turn to the LLM."""
        strategy, client, _ = _build(completion_mode='manual')
        client.event_loop = asyncio.get_running_loop()
        _start_session(client, manual=True)
        strategy._text = 'what time is it in tokyo'  # noqa: SLF001

        parent = AsyncMock()
        with patch.object(_PARENT, 'trigger_user_turn_stopped', new=parent), \
                patch.object(module, 'MANUAL_RELEASE_QUIET_WINDOW_SECONDS', 0.01), \
                patch.object(module, 'MANUAL_RELEASE_MAX_WAIT_SECONDS', 0.1):
            _end_session(client)
            await asyncio.sleep(0.06)

        self.assertEqual(parent.await_count, 1)  # noqa: PT009
        # Release must NOT re-dispatch StopListening (already stopped).
        self.assertEqual(client.dispatch.call_count, 0)  # noqa: PT009

    async def test_manual_release_no_flush_when_empty(self) -> None:
        """An empty hold (no transcript) flushes nothing."""
        strategy, client, _ = _build(completion_mode='manual')
        client.event_loop = asyncio.get_running_loop()
        _start_session(client, manual=True)
        strategy._text = ''  # noqa: SLF001

        parent = AsyncMock()
        with patch.object(_PARENT, 'trigger_user_turn_stopped', new=parent), \
                patch.object(module, 'MANUAL_RELEASE_QUIET_WINDOW_SECONDS', 0.01), \
                patch.object(module, 'MANUAL_RELEASE_MAX_WAIT_SECONDS', 0.1):
            _end_session(client)
            await asyncio.sleep(0.06)

        self.assertEqual(parent.await_count, 0)  # noqa: PT009

    async def test_silence_release_does_not_start_settle(self) -> None:
        """A silence-policy session end never starts a manual release flush."""
        strategy, client, _ = _build(silence_timeout_seconds=2.0)
        client.event_loop = asyncio.get_running_loop()
        _start_session(client, manual=False)
        strategy._text = 'hello'  # noqa: SLF001

        parent = AsyncMock()
        with patch.object(_PARENT, 'trigger_user_turn_stopped', new=parent), \
                patch.object(module, 'MANUAL_RELEASE_QUIET_WINDOW_SECONDS', 0.01), \
                patch.object(module, 'MANUAL_RELEASE_MAX_WAIT_SECONDS', 0.1):
            _end_session(client)
            await asyncio.sleep(0.06)

        self.assertEqual(parent.await_count, 0)  # noqa: PT009
        self.assertIsNone(strategy._release_settle_task)  # noqa: PT009, SLF001

    async def test_interruption_cancels_release_settle(self) -> None:
        """An InterruptionFrame ("okay enough") aborts a pending release flush."""
        strategy, client, _ = _build(completion_mode='manual')
        client.event_loop = asyncio.get_running_loop()
        _start_session(client, manual=True)
        strategy._text = 'something'  # noqa: SLF001

        parent = AsyncMock()
        parent_process = AsyncMock(return_value=ProcessFrameResult.CONTINUE)
        with patch.object(_PARENT, 'trigger_user_turn_stopped', new=parent), \
                patch.object(_PARENT, 'process_frame', new=parent_process), \
                patch.object(module, 'MANUAL_RELEASE_QUIET_WINDOW_SECONDS', 1.0), \
                patch.object(module, 'MANUAL_RELEASE_MAX_WAIT_SECONDS', 2.0):
            _end_session(client)
            await asyncio.sleep(0)  # let the settle task start
            await strategy.process_frame(InterruptionFrame())
            await asyncio.sleep(0.05)

        self.assertEqual(parent.await_count, 0)  # noqa: PT009
        self.assertIsNone(strategy._release_settle_task)  # noqa: PT009, SLF001

    async def test_phrase_trigger_fires_super_regardless_of_policy(self) -> None:
        """trigger_phrase_end_of_turn always fires the parent user-turn-stop."""
        strategy, client, _ = _build(
            completion_mode='silence',
            end_of_turn_phrases=("i'm done",),
        )
        parent = AsyncMock()
        with patch.object(_PARENT, 'trigger_user_turn_stopped', new=parent):
            await strategy.trigger_phrase_end_of_turn()
        self.assertEqual(parent.await_count, 1)  # noqa: PT009
        self.assertEqual(client.dispatch.call_count, 0)  # noqa: PT009

    async def test_cleanup_unsubscribes_both(self) -> None:
        """Cleanup unsubscribes the policy watcher and the listening autorun."""
        strategy, client, watcher = _build(silence_timeout_seconds=2.0)
        self.assertEqual(len(watcher._subscribers), 1)  # noqa: PT009, SLF001

        with patch.object(_PARENT, 'cleanup', new=AsyncMock()):
            await strategy.cleanup()

        self.assertEqual(len(watcher._subscribers), 0)  # noqa: PT009, SLF001
        client.unsubscribe.assert_called_once()


if __name__ == '__main__':
    unittest.main()
