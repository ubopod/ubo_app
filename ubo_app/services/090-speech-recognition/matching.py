"""Pure matching logic for the armed Vosk grammar.

Kept free of the store and the engines so it can be reasoned about — and tested —
on its own. ``EnginesManager`` composes a grammar from these phrases and routes
each recognition back through :func:`match_recognition`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pattern import PatternError, expand_pattern

from ubo_app.logger import logger
from ubo_app.store.services.speech_recognition import (
    SpeechRecognitionIntent,
    SpeechRecognitionReportIntentDetectionAction,
    SpeechRecognitionReportWakeWordDetectionAction,
    WakeMode,
    WakeWordEngineConfig,
    WakeWordEngineName,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


def expand_phrases(phrases: Sequence[str]) -> list[str]:
    """Expand each utterance pattern to its concrete phrases (lowercased).

    A malformed pattern falls back to the raw line as a literal so a bad pattern
    can never break recognition for the whole command set.
    """
    expanded: list[str] = []
    for phrase in phrases:
        try:
            expanded.extend(expand_pattern(phrase))
        except PatternError:
            logger.warning(
                'Invalid utterance pattern; using it as a literal phrase',
                extra={'pattern': phrase},
            )
            expanded.append(phrase)
    return [phrase.lower() for phrase in expanded]


def stop_talking_triggers(
    configs: Sequence[WakeWordEngineConfig],
) -> dict[str, str]:
    """Map each enabled Vosk stop-talking phrase to its trigger id.

    These get folded into the grammar of every armed recognition. Vosk's grammar
    is whatever the *ongoing* recognition asks for and nothing else — its wake
    words are dropped while one is active (``vosk_engine._phrases``), and
    ``SpeechRecognitionMixin.report`` never falls through to the wake mixin
    either. So without this, arming a recognition would take the stop phrase deaf
    for the whole window — exactly when a quick-chat session wants barge-in most.
    """
    return {
        trigger.value.lower(): trigger.id
        for config in configs
        if config.engine is WakeWordEngineName.VOSK and config.enabled
        for trigger in config.triggers
        if trigger.mode is WakeMode.STOP_TALKING
    }


def match_recognition(
    text: str,
    intents: Sequence[SpeechRecognitionIntent],
    stop_triggers: dict[str, str],
) -> (
    SpeechRecognitionReportIntentDetectionAction
    | SpeechRecognitionReportWakeWordDetectionAction
    | None
):
    """Resolve a recognition from the armed grammar to the action it stands for.

    Commands are matched first (and exactly), so a command phrase that happens to
    contain the stop phrase — "stop the music" against a "stop" trigger — still
    runs the command. A stop phrase is then matched as a substring, mirroring how
    the wake mixin matches wake words.

    Returns ``None`` when the recognition is neither, which for a grammar-
    constrained engine mostly means ``[unk]`` noise.
    """
    lowered = text.lower()

    if intent := next(
        (intent for intent in intents if lowered in expand_phrases(intent.phrases)),
        None,
    ):
        return SpeechRecognitionReportIntentDetectionAction(intent=intent, text=text)

    trigger_id = next(
        (
            trigger_id
            for phrase, trigger_id in stop_triggers.items()
            if phrase in lowered
        ),
        None,
    )
    if trigger_id is not None:
        # Hand it to the normal wake path, which maps STOP_TALKING to silencing
        # the assistant (or dismissing the command window).
        return SpeechRecognitionReportWakeWordDetectionAction(
            engine_name=WakeWordEngineName.VOSK.value,
            trigger_id=trigger_id,
            phrase=text,
        )

    return None
