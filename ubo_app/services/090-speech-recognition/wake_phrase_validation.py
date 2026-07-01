"""Validate user-entered wake/stop phrases against the Kaldi/Vosk vocabulary.

Pure functions — the loaded ``vosk.Model`` is passed in. The model has no
plaintext lexicon (vocabulary is compiled into ``graph/Gr.fst``); membership is
checked via ``model.vosk_model_find_word(word)`` which returns a positive word-id
when in-vocabulary and a negative sentinel when out-of-vocabulary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from vosk import Model

    from ubo_app.store.services.speech_recognition import (
        SpeechRecognitionState,
        WakeMode,
    )

MIN_WORDS = 2


def split_words(phrase: str) -> list[str]:
    """Split on whitespace only — apostrophes stay inside tokens (contractions)."""
    return phrase.casefold().split()


def out_of_vocabulary_words(words: Sequence[str], model: Model) -> list[str]:
    """Return the words not present in the model's Kaldi vocabulary."""
    return [word for word in words if model.vosk_model_find_word(word) < 0]


def validate_phrase(
    phrase: str,
    model: Model,
    *,
    min_words: int = MIN_WORDS,
) -> list[str]:
    """Return human-readable problems with *phrase*, or an empty list if valid."""
    problems: list[str] = []
    words = split_words(phrase)
    if len(words) < min_words:
        problems.append(f'Use at least {min_words} words (a single word is too short).')
    if any(not word.replace("'", '').isalpha() for word in words):
        problems.append('Use only letters (and apostrophes for contractions).')
    oov = out_of_vocabulary_words(words, model)
    if oov:
        problems.append(
            'These words are not recognised by the speech model: '
            + ', '.join(oov)
            + '.',
        )
    return problems


# Field-label per mode, for collision messages.
_MODE_LABELS: dict[str, str] = {
    'intents': 'Command Interface',
    'quick_chat': 'Quick Chat',
    'conversation': 'Conversation',
    'stop_talking': 'Stop Talking',
}


def phrase_collisions(
    candidate: str,
    mode: WakeMode,
    state: SpeechRecognitionState,
) -> list[str]:
    """Return messages if *candidate* duplicates another phrase in *state*.

    Two slots sharing a phrase would let reducer match-ordering silently decide
    behaviour, so a new value must be unique across all *other* slots' phrases and
    the conversation end-phrase alternatives.
    """
    normalized = candidate.casefold()
    problems = [
        f'Already used by {_MODE_LABELS[slot.mode.value]}.'
        for slot in state.wake_slots
        if slot.mode != mode
        and any(phrase.casefold() == normalized for phrase in slot.phrases)
    ]
    end_phrases = state.conversation_end_phrases
    if any(phrase.casefold() == normalized for phrase in end_phrases):
        problems.append('Already used by a Conversation End phrase.')
    return problems
