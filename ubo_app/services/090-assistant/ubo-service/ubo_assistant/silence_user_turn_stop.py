"""Policy-driven user-turn stop strategy.

Reuses pipecat's built-in ``SpeechTimeoutUserTurnStopStrategy`` for the
user-turn signalling that lets the LLM know the user is done speaking. On
top of that, when the active assistant policy specifies a session-level
``silence_timeout_seconds``, this strategy ALSO dispatches an
``AssistantStopListeningAction`` back to ubo-core so the global listening
state ends after silence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from pipecat.turns.user_stop.speech_timeout_user_turn_stop_strategy import (
    SpeechTimeoutUserTurnStopStrategy,
)
from ubo_bindings.ubo.v1 import (
    Action,
    AssistantStopListeningAction,
    AssistantStopReasonUnion,
    SilenceTimeoutStopReason,
)

if TYPE_CHECKING:
    from ubo_bindings.client import UboRPCClient

    from ubo_assistant.policy_watcher import PolicyContext, PolicyWatcher


_DEFAULT_USER_SPEECH_TIMEOUT = 0.6
"""Pipecat's documented default for ``user_speech_timeout``."""


class UboPolicyAwareUserTurnStopStrategy(SpeechTimeoutUserTurnStopStrategy):
    """Per-policy silence-timeout strategy that ends the listening session."""

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

    def _apply_policy(self, policy: PolicyContext) -> None:
        """Update the underlying timeout when the active policy changes."""
        timeout = policy.silence_timeout_seconds
        if timeout is not None and timeout > 0:
            self._user_speech_timeout = timeout
        else:
            self._user_speech_timeout = self._fallback_timeout

    async def trigger_user_turn_stopped(self) -> None:
        """Fire the user-turn-stop signal, then optionally end the session."""
        captured_timeout = self._user_speech_timeout
        policy = self._policy_watcher.context

        await super().trigger_user_turn_stopped()

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

    async def cleanup(self) -> None:
        """Unsubscribe from the policy watcher on teardown."""
        try:
            self._unsubscribe()
        except Exception:  # pragma: no cover - defensive
            logger.exception('Error unsubscribing UboPolicyAwareUserTurnStopStrategy')
        await super().cleanup()
