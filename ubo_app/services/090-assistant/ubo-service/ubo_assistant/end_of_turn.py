"""End-of-turn phrase detection FrameProcessor.

Inspects ``TranscriptionFrame`` text emitted by the active STT provider and,
when the user finishes their turn with one of the policy's configured end
phrases (e.g. *"i'm done"*), dispatches an ``AssistantStopListeningAction``
back to ubo-core with an :class:`EndOfTurnPhraseStopReason`.

Frames are forwarded downstream unchanged so the rest of the pipeline (LLM,
TTS) is unaffected.
"""

from __future__ import annotations

import string
from typing import TYPE_CHECKING

from loguru import logger
from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from ubo_bindings.ubo.v1 import (
    Action,
    AssistantStopListeningAction,
    AssistantStopReasonUnion,
    EndOfTurnPhraseStopReason,
)

if TYPE_CHECKING:
    from ubo_bindings.client import UboRPCClient

    from ubo_assistant.policy_watcher import PolicyWatcher


_PUNCTUATION_TRANSLATION = str.maketrans('', '', string.punctuation)


def _normalise(text: str) -> str:
    return text.translate(_PUNCTUATION_TRANSLATION).strip().casefold()


def match_end_of_turn_phrase(
    text: str,
    phrases: tuple[str, ...],
) -> str | None:
    """Return the matching phrase if *text* ends with any of *phrases*."""
    if not text or not phrases:
        return None
    normalised = _normalise(text)
    for phrase in phrases:
        normalised_phrase = _normalise(phrase)
        if not normalised_phrase:
            continue
        if normalised.endswith(normalised_phrase):
            return phrase
    return None


class EndOfTurnPhraseDetector(FrameProcessor):
    """Pass-through FrameProcessor that detects end-of-turn phrases.

    Inert when the active policy has no ``end_of_turn_phrases``.
    """

    def __init__(
        self,
        *,
        client: UboRPCClient,
        policy_watcher: PolicyWatcher,
    ) -> None:
        """Wire the detector to its UBO RPC client and policy watcher."""
        super().__init__()
        self._client = client
        self._policy_watcher = policy_watcher

    async def process_frame(
        self,
        frame: Frame,
        direction: FrameDirection,
    ) -> None:
        """Inspect TranscriptionFrames, then forward every frame unchanged."""
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            policy = self._policy_watcher.context
            phrase = match_end_of_turn_phrase(
                frame.text,
                policy.end_of_turn_phrases,
            )
            if phrase is not None:
                logger.info(
                    'End-of-turn phrase matched',
                    extra={'phrase': phrase, 'text': frame.text},
                )
                self._client.dispatch(
                    action=Action(
                        assistant_stop_listening_action=AssistantStopListeningAction(
                            reason=AssistantStopReasonUnion(
                                end_of_turn_phrase_stop_reason=(
                                    EndOfTurnPhraseStopReason(
                                        phrase=phrase,
                                        matched_text=frame.text,
                                    )
                                ),
                            ),
                        ),
                    ),
                )

        await self.push_frame(frame, direction)
