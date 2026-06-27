"""Unit tests for wake-phrase validation (pure, no real Vosk model).

The validator checks word count, character set, Kaldi-vocabulary membership
(via ``model.vosk_model_find_word``), and cross-phrase collisions. A fake model
stands in for ``vosk.Model`` so no model download is needed.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/090-speech-recognition'


class _FakeModel:
    """Vocabulary stub: known words resolve, everything else is OOV (-1)."""

    def __init__(self, vocabulary: set[str]) -> None:
        self._vocabulary = vocabulary

    def vosk_model_find_word(self, word: str) -> int:
        return 1 if word in self._vocabulary else -1


def _load_validation(monkeypatch: pytest.MonkeyPatch) -> Any:  # noqa: ANN401
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())
    spec = importlib.util.spec_from_file_location(
        'wake_phrase_validation_under_test',
        SERVICE_PATH / 'wake_phrase_validation.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_valid_multiword_in_vocabulary(monkeypatch: pytest.MonkeyPatch) -> None:
    """A multi-word, in-vocabulary phrase has no problems."""
    module = _load_validation(monkeypatch)
    model = _FakeModel({'hey', 'quick', 'question'})
    assert module.validate_phrase('hey quick question', model) == []


def test_single_word_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A single word is too short."""
    module = _load_validation(monkeypatch)
    model = _FakeModel({'hello'})
    problems = module.validate_phrase('hello', model)
    assert any('at least' in p for p in problems)


def test_out_of_vocabulary_word_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An out-of-vocabulary word is named in the problems list."""
    module = _load_validation(monkeypatch)
    model = _FakeModel({'hey', 'there'})
    problems = module.validate_phrase('hey gizmo', model)
    assert any('gizmo' in p for p in problems)


def test_contractions_split_on_whitespace_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apostrophes stay inside the token, so a contraction is one vocab word."""
    module = _load_validation(monkeypatch)
    model = _FakeModel({"let's", 'have', 'fun'})
    assert module.validate_phrase("let's have fun", model) == []
    assert module.out_of_vocabulary_words(["let's"], model) == []


def test_phrase_collision_across_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    """A phrase duplicating another mode's phrase collides; its own does not."""
    module = _load_validation(monkeypatch)
    sr = importlib.import_module('ubo_app.store.services.speech_recognition')

    def _trigger(trigger_id: str, mode: Any, value: str) -> Any:  # noqa: ANN401
        return SimpleNamespace(id=trigger_id, mode=mode, value=value)

    state = SimpleNamespace(
        wake_engines=(
            SimpleNamespace(
                engine=sr.WakeWordEngineName.VOSK,
                triggers=(
                    _trigger('t-intents', sr.WakeMode.INTENTS, 'short voice command'),
                    _trigger('t-quick', sr.WakeMode.QUICK_CHAT, 'hey quick question'),
                    _trigger(
                        't-conv',
                        sr.WakeMode.CONVERSATION,
                        "let's have a conversation",
                    ),
                    _trigger('t-stop', sr.WakeMode.STOP_TALKING, 'okay enough'),
                ),
            ),
        ),
        conversation_end_phrases=('i am done talking',),
    )

    # Candidate duplicates the conversation phrase while editing quick-chat.
    problems = module.phrase_collisions(
        "let's have a conversation",
        sr.WakeWordEngineName.VOSK,
        state,
        exclude_trigger_id='t-quick',
    )
    assert problems

    # Editing a trigger to its own current value is not a collision.
    assert (
        module.phrase_collisions(
            'hey quick question',
            sr.WakeWordEngineName.VOSK,
            state,
            exclude_trigger_id='t-quick',
        )
        == []
    )


def test_openwakeword_model_collision_is_engine_wide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An OWW model stem must be unique across the whole engine.

    The engine maps each stem to a single trigger id, so the same stem in *any*
    two triggers (including the same mode) would silently collapse to one binding.
    """
    module = _load_validation(monkeypatch)
    sr = importlib.import_module('ubo_app.store.services.speech_recognition')

    state = SimpleNamespace(
        wake_engines=(
            SimpleNamespace(
                engine=sr.WakeWordEngineName.OPENWAKEWORD,
                triggers=(
                    SimpleNamespace(
                        id='oww-conv',
                        mode=sr.WakeMode.CONVERSATION,
                        value='hey_jarvis_v0.1',
                    ),
                ),
            ),
        ),
        conversation_end_phrases=(),
    )

    # Same stem in a different mode collides.
    assert module.phrase_collisions(
        'hey_jarvis_v0.1',
        sr.WakeWordEngineName.OPENWAKEWORD,
        state,
    )
    # Same stem in the SAME mode now collides too (it would otherwise collapse).
    assert module.phrase_collisions(
        'hey_jarvis_v0.1',
        sr.WakeWordEngineName.OPENWAKEWORD,
        state,
    )
    # Re-selecting the same model while editing that trigger does not collide.
    assert (
        module.phrase_collisions(
            'hey_jarvis_v0.1',
            sr.WakeWordEngineName.OPENWAKEWORD,
            state,
            exclude_trigger_id='oww-conv',
        )
        == []
    )
