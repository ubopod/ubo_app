"""Subscribes to ``state.assistant.active_policy`` and exposes a snapshot.

The pipeline-side processors (``EndOfTurnPhraseDetector`` and the silence
``UserTurnStopStrategy``) react to changes in the active policy without
each opening their own autorun subscription. This module owns one
subscription and fans out to subscribers.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_bindings.client import UboRPCClient


@dataclass(frozen=True)
class PolicyContext:
    """Immutable snapshot of the active assistant trigger policy."""

    silence_timeout_seconds: float | None = None
    end_of_turn_phrases: tuple[str, ...] = ()
    completion_mode: str = 'silence'

    @classmethod
    def empty(cls) -> PolicyContext:
        """Return an inert policy (no silence stop, no phrase stop)."""
        return cls()

    @property
    def is_manual(self) -> bool:
        """True for push-to-talk policies that complete only on session end."""
        return self.completion_mode == 'manual'


class PolicyWatcher:
    """Single autorun subscription that publishes :class:`PolicyContext`."""

    def __init__(self, client: UboRPCClient) -> None:
        """Start subscribing to the active policy state slice."""
        self._client = client
        self._context = PolicyContext.empty()
        self._subscribers: list[Callable[[PolicyContext], None]] = []

        @client.autorun(['state.assistant.active_policy'])
        def _handle(data: list) -> None:
            self._update_from_autorun_data(data)

        # Keep a reference so the closure isn't garbage-collected.
        self._autorun_handle = _handle

    @property
    def context(self) -> PolicyContext:
        """Current snapshot. Reads are cheap; values may change between reads."""
        return self._context

    def subscribe(
        self,
        callback: Callable[[PolicyContext], None],
    ) -> Callable[[], None]:
        """Register *callback* to be invoked on every policy transition.

        The callback is invoked once immediately with the current snapshot so
        late subscribers don't miss the active state. Returns an unsubscribe
        callable.
        """
        self._subscribers.append(callback)
        try:
            callback(self._context)
        except Exception:  # pragma: no cover - defensive
            logger.exception('PolicyWatcher initial subscriber call raised')

        def _unsubscribe() -> None:
            with contextlib.suppress(ValueError):
                self._subscribers.remove(callback)

        return _unsubscribe

    def _update_from_autorun_data(self, data: list) -> None:
        policy_msg = data[0] if data else None
        new_context = _policy_message_to_context(policy_msg)
        if new_context == self._context:
            return
        logger.info(
            'Assistant policy updated',
            extra={
                'silence_timeout_seconds': new_context.silence_timeout_seconds,
                'end_of_turn_phrases': new_context.end_of_turn_phrases,
                'completion_mode': new_context.completion_mode,
            },
        )
        self._context = new_context
        for subscriber in list(self._subscribers):
            try:
                subscriber(new_context)
            except Exception:  # pragma: no cover - defensive
                logger.exception('PolicyWatcher subscriber raised')


def _policy_message_to_context(policy_msg: object) -> PolicyContext:
    """Map a betterproto AssistantTriggerPolicy (or None) to PolicyContext."""
    if policy_msg is None:
        return PolicyContext.empty()

    silence_timeout = getattr(policy_msg, 'silence_timeout_seconds', None)
    # betterproto delivers ``completion_mode`` as the generated enum; map its
    # name to our lowercase string. Any unset / unspecified value is silence.
    mode_msg = getattr(policy_msg, 'completion_mode', None)
    mode_name = getattr(mode_msg, 'name', '') or ''
    completion_mode = 'manual' if mode_name == 'MANUAL' else 'silence'
    phrases_msg = getattr(policy_msg, 'end_of_turn_phrases', None)
    phrases: tuple[str, ...] = ()
    if phrases_msg is not None:
        items = getattr(phrases_msg, 'items', None)
        if items:
            phrases = tuple(items)

    return PolicyContext(
        silence_timeout_seconds=silence_timeout,
        end_of_turn_phrases=phrases,
        completion_mode=completion_mode,
    )
