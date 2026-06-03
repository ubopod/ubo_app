"""End-of-turn phrase detection FrameProcessor.

Inspects ``TranscriptionFrame`` text emitted by the active STT provider and,
when the user finishes their turn with one of the policy's configured end
phrases (e.g. *"i'm done"*), dispatches an ``AssistantStopListeningAction``
back to ubo-core with an :class:`EndOfTurnPhraseStopReason`.

Frames are forwarded downstream unchanged so the rest of the pipeline (LLM,
TTS) is unaffected.
"""

from __future__ import annotations

import re
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
    from ubo_assistant.silence_user_turn_stop import (
        UboPolicyAwareUserTurnStopStrategy,
    )


_APOSTROPHES = ("'", chr(0x2019))  # straight and typographic apostrophe
_WORD_RE = re.compile(r'\w+')
_MAX_TRAILING_WORDS = 2
"""How many words may follow an end phrase and still count as end-of-utterance.

Lets verbose completions ("i'm done talking", "i'm done talking now") trigger a
stop while longer continuations ("i'm done thinking, what next") do not.
"""


def _words(text: str) -> list[str]:
    """Split *text* into lowercase word tokens.

    Apostrophes are removed so contractions collapse (``that's`` → ``thats``);
    every other punctuation char acts as a word boundary, so a period inserted
    mid-phrase by the STT (``done. talking``, ``done.talking``, ``done .
    talking``) tokenises identically to the configured phrase.
    """
    lowered = text.casefold()
    for apostrophe in _APOSTROPHES:
        lowered = lowered.replace(apostrophe, '')
    return _WORD_RE.findall(lowered)


def match_end_of_turn_phrase(
    text: str,
    phrases: tuple[str, ...],
) -> str | None:
    """Return the matching phrase if *text* ends with any of *phrases*.

    Matching is on word tokens, so punctuation and whitespace the STT inserts
    between words never blocks a match. Up to ``_MAX_TRAILING_WORDS`` words may
    follow the phrase, so spoken completions ("i'm done talking") still count as
    end-of-utterance.
    """
    if not text or not phrases:
        return None
    text_words = _words(text)
    total = len(text_words)
    for phrase in phrases:
        phrase_words = _words(phrase)
        count = len(phrase_words)
        if not count or count > total:
            continue
        latest_start = total - count
        earliest_start = max(0, latest_start - _MAX_TRAILING_WORDS)
        for start in range(latest_start, earliest_start - 1, -1):
            if text_words[start : start + count] == phrase_words:
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
        user_turn_stop_strategy: UboPolicyAwareUserTurnStopStrategy,
    ) -> None:
        """Wire the detector to its UBO RPC client, policy watcher, strategy."""
        super().__init__()
        self._client = client
        self._policy_watcher = policy_watcher
        self._user_turn_stop_strategy = user_turn_stop_strategy

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
                    'End-of-turn phrase matched; ending turn and dropping the '
                    'phrase transcript so it is not sent to the LLM',
                    extra={'phrase': phrase, 'text': frame.text},
                )
                await self._user_turn_stop_strategy.trigger_phrase_end_of_turn()
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
                # Swallow the end-phrase transcript: it is a control command,
                # not content. Forwarding it would add it to the user aggregator
                # and prompt the LLM to reply to "i'm done".
                return

        await self.push_frame(frame, direction)
