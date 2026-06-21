"""Policy-driven user-turn stop strategy.

Wraps pipecat's ``SpeechTimeoutUserTurnStopStrategy`` and adapts it per active
assistant policy:

- **Silence** policies (conversation, quick chat): the turn completes after the
  policy's ``silence_timeout_seconds`` of continuous quiet (conversation also
  early-completes on an end-of-turn phrase). On completion this strategy
  dispatches ``AssistantStopListeningAction`` so the global listening state ends.
- **Manual / push-to-talk** policies (keypad, infrared): silence never completes
  the turn while listening — the user is holding the button / has toggled
  listening on. The turn flushes to the LLM only when the session ends
  (``is_listening`` True→False), after a bounded settle that waits for the
  streaming STT to finalize the user's last words.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger
from pipecat.frames.frames import InterruptionFrame, TranscriptionFrame
from pipecat.turns.user_stop.speech_timeout_user_turn_stop_strategy import (
    SpeechTimeoutUserTurnStopStrategy,
)
from ubo_bindings.ubo.v1 import (
    Action,
    AssistantStopListeningAction,
    AssistantStopReasonUnion,
    SilenceTimeoutStopReason,
)

from ubo_assistant.constants import (
    MANUAL_RELEASE_MAX_WAIT_SECONDS,
    MANUAL_RELEASE_QUIET_WINDOW_SECONDS,
)
from ubo_assistant.policy_watcher import _policy_message_to_context

if TYPE_CHECKING:
    from pipecat.frames.frames import Frame
    from pipecat.turns.types import ProcessFrameResult
    from ubo_bindings.client import UboRPCClient

    from ubo_assistant.policy_watcher import PolicyContext, PolicyWatcher


_DEFAULT_USER_SPEECH_TIMEOUT = 0.6
"""Pipecat's documented default for ``user_speech_timeout``."""


class UboPolicyAwareUserTurnStopStrategy(SpeechTimeoutUserTurnStopStrategy):
    """Per-policy strategy: silence-timeout completion or manual (PTT) flush."""

    def __init__(
        self,
        *,
        client: UboRPCClient,
        policy_watcher: PolicyWatcher,
        fallback_timeout: float = _DEFAULT_USER_SPEECH_TIMEOUT,
    ) -> None:
        """Wire to its UBO RPC client and policy watcher."""
        super().__init__(user_speech_timeout=fallback_timeout)
        self._client = client
        self._policy_watcher = policy_watcher
        self._fallback_timeout = fallback_timeout
        self._unsubscribe = policy_watcher.subscribe(self._apply_policy)

        # Manual (PTT) session tracking. ``_session_is_manual`` is latched at the
        # rising edge of ``is_listening`` from the active policy in the SAME
        # state snapshot, because the policy resets to None atomically with
        # ``is_listening=False`` and would otherwise be unreadable at release.
        self._is_listening = False
        self._session_is_manual = False
        self._release_settle_task: asyncio.Task[None] | None = None
        self._transcript_event = asyncio.Event()
        self._listening_unsubscribe = client.autorun(
            ['state.assistant.is_listening', 'state.assistant.active_policy'],
        )(self._on_listening_changed)

    def _apply_policy(self, policy: PolicyContext) -> None:
        """Update the underlying timeout when the active policy changes."""
        timeout = policy.silence_timeout_seconds
        if timeout is not None and timeout > 0:
            self._user_speech_timeout = timeout
        else:
            self._user_speech_timeout = self._fallback_timeout

    async def process_frame(self, frame: Frame) -> ProcessFrameResult:
        """Delegate to the base strategy, observing interruptions/transcripts.

        Always delegates so the base keeps its accumulated ``_text`` current. An
        ``InterruptionFrame`` (barge-in / "okay enough") aborts any in-flight
        manual release settle so it can't flush an already-cleared turn. A late
        ``TranscriptionFrame`` (the trailing-silence-finalized last words) re-arms
        the settle's quiet window so the flush waits for it.
        """
        if isinstance(frame, InterruptionFrame):
            self._cancel_release_settle()
        result = await super().process_frame(frame)
        if isinstance(frame, TranscriptionFrame) and self._release_settle_task:
            self._transcript_event.set()
        return result

    async def trigger_user_turn_stopped(self) -> None:
        """Complete the turn on silence, unless this is a held manual session.

        While a push-to-talk session is still listening, silence-driven
        completion is suppressed entirely — the turn flushes only on release
        (see :meth:`_flush_manual_turn`). For silence policies, complete normally
        and dispatch ``AssistantStopListeningAction`` to end the session.
        """
        if self._session_is_manual and self._is_listening:
            logger.debug(
                'Manual (PTT) session still listening: '
                'suppressing silence-driven turn stop',
            )
            return

        captured_timeout = self._user_speech_timeout
        await super().trigger_user_turn_stopped()

        policy = self._policy_watcher.context
        if (
            policy.silence_timeout_seconds is not None
            and policy.silence_timeout_seconds > 0
        ):
            logger.info(
                'Silence policy triggered; dispatching AssistantStopListeningAction',
                extra={'silence_seconds': captured_timeout},
            )
            self._client.dispatch(
                action=Action(
                    assistant_stop_listening_action=AssistantStopListeningAction(
                        reason=AssistantStopReasonUnion(
                            silence_timeout_stop_reason=SilenceTimeoutStopReason(
                                silence_seconds=captured_timeout,
                            ),
                        ),
                    ),
                ),
            )

    async def trigger_phrase_end_of_turn(self) -> None:
        """Force the user-turn-stop signal from an end-of-turn phrase match.

        Called by :class:`~ubo_assistant.end_of_turn.EndOfTurnPhraseDetector`
        when the user's transcript ends with one of the policy's end phrases.
        Unconditionally invokes the parent's ``trigger_user_turn_stopped`` so the
        user aggregator emits ``UserStoppedSpeakingFrame`` and pushes the
        accumulated context to the LLM, regardless of policy.
        """
        await super().trigger_user_turn_stopped()

    def _on_listening_changed(self, results: list) -> None:
        """Latch manual sessions on start; flush manual sessions on release.

        The autorun delivers one unpacked value per selector: ``is_listening`` is
        a scalar wrapper (read via ``.value``), while ``active_policy`` is the
        ``AssistantTriggerPolicy`` message itself (or ``None``) — NOT a wrapper,
        so it must be passed straight to the policy mapper.
        """
        is_listening = bool(results[0].value) if results else False
        active_policy_msg = results[1] if len(results) > 1 else None
        was_listening = self._is_listening
        self._is_listening = is_listening

        if is_listening and not was_listening:
            # Session start: latch whether this session is push-to-talk, reading
            # the policy from the same snapshot that turned listening on.
            self._session_is_manual = _policy_message_to_context(
                active_policy_msg,
            ).is_manual
            self._cancel_release_settle()
        elif was_listening and not is_listening and self._session_is_manual:
            # Manual session ended (button release / listen toggle off): flush the
            # accumulated turn once the trailing-silence transcript settles.
            self._start_release_settle()

    def _cancel_release_settle(self) -> None:
        """Stop any in-progress manual release settle."""
        task = self._release_settle_task
        if task is not None and not task.done():
            task.cancel()
        self._release_settle_task = None

    def _start_release_settle(self) -> None:
        """Begin the bounded settle that flushes the held turn after release."""
        self._cancel_release_settle()
        self._transcript_event.clear()
        self._release_settle_task = self._client.event_loop.create_task(
            self._release_settle_handler(),
        )

    async def _release_settle_handler(self) -> None:
        """Wait for the final transcript to settle, then flush the manual turn.

        Re-arms a short quiet window on each incoming transcript (set in
        :meth:`process_frame`), bounded by a hard maximum so a never-finalizing
        STT can't hang the turn. Cancelled by an ``InterruptionFrame``.
        """
        loop = self._client.event_loop
        deadline = loop.time() + MANUAL_RELEASE_MAX_WAIT_SECONDS
        try:
            while loop.time() < deadline:
                try:
                    await asyncio.wait_for(
                        self._transcript_event.wait(),
                        timeout=MANUAL_RELEASE_QUIET_WINDOW_SECONDS,
                    )
                except TimeoutError:
                    break  # quiet window elapsed with no new transcript
                self._transcript_event.clear()  # got a transcript, re-arm
        except asyncio.CancelledError:
            self._release_settle_task = None
            return
        self._release_settle_task = None
        await self._flush_manual_turn()

    async def _flush_manual_turn(self) -> None:
        """Flush the accumulated push-to-talk turn to the LLM.

        Bypasses the manual gate in :meth:`trigger_user_turn_stopped` via
        ``super()`` and does NOT re-dispatch ``AssistantStopListeningAction`` —
        listening already ended (that edge is what triggered this). No-ops when
        nothing was captured (e.g. an interrupted / empty hold).
        """
        if not self._text:
            logger.debug('Manual release settle: nothing captured, not flushing')
            return
        logger.info('Manual (PTT) release: flushing accumulated turn to the LLM')
        await super().trigger_user_turn_stopped()

    async def cleanup(self) -> None:
        """Unsubscribe from the watcher and autorun, cancel pending settle."""
        self._cancel_release_settle()
        for unsubscribe in (self._unsubscribe, self._listening_unsubscribe):
            try:
                unsubscribe()
            except Exception:  # pragma: no cover - defensive
                logger.exception(
                    'Error unsubscribing UboPolicyAwareUserTurnStopStrategy',
                )
        await super().cleanup()
