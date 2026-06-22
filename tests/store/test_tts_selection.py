"""Tests for the screen reader's local-TTS preference resolution.

``first_configured_local_tts`` picks the highest-priority local TTS engine that
is set up (per the assistant's ``provider_setup_status``), preferring Piper over
Kokoro, and returns ``None`` when no local engine is configured (caller falls
back to the assistant's default TTS).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

    import pytest


SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/010-speech-synthesis'


def _load(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())
    spec = importlib.util.spec_from_file_location(
        'speech_synthesis_tts_selection',
        SERVICE_PATH / 'tts_selection.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_prefers_piper_when_both_local_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Piper wins over Kokoro when both local engines are set up."""
    module = _load(monkeypatch)
    result = module.first_configured_local_tts({'piper': True, 'kokoro': True})
    assert result is not None
    assert result.value == 'piper'


def test_falls_back_to_kokoro_when_piper_not_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kokoro is chosen when Piper is not set up but Kokoro is."""
    module = _load(monkeypatch)
    result = module.first_configured_local_tts({'piper': False, 'kokoro': True})
    assert result is not None
    assert result.value == 'kokoro'


def test_none_when_only_cloud_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No local engine configured → None (caller uses the assistant default)."""
    module = _load(monkeypatch)
    result = module.first_configured_local_tts(
        {'piper': False, 'kokoro': False, 'openai': True},
    )
    assert result is None


def test_none_on_empty_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty setup status yields None."""
    module = _load(monkeypatch)
    assert module.first_configured_local_tts({}) is None


def test_has_any_tts_true_for_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured local engine counts as having a TTS."""
    module = _load(monkeypatch)
    assert module.has_any_tts_configured({'piper': True}) is True


def test_has_any_tts_true_for_cloud(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured cloud engine counts as having a TTS."""
    module = _load(monkeypatch)
    assert module.has_any_tts_configured({'elevenlabs': True}) is True


def test_has_any_tts_false_when_none_or_unrelated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No TTS set up → False; non-TTS keys are ignored."""
    module = _load(monkeypatch)
    assert module.has_any_tts_configured({}) is False
    assert module.has_any_tts_configured({'piper': False, 'openai': False}) is False
    # 'vosk' is an STT engine, not a TTS — must not count.
    assert module.has_any_tts_configured({'vosk': True}) is False
