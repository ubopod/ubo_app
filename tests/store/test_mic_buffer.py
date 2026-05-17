"""Tests for the rolling ``MicBuffer`` in the speech-recognition service.

Loads the module via ``importlib.util.spec_from_file_location`` so the test
runs independently of the rest of the service (which depends on hardware
imports like ``vosk_engine`` / ``google_engine``).
"""

from __future__ import annotations

import importlib.util
import sys
import wave
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

    import pytest


SERVICE_PATH = (
    Path(__file__).parents[2] / 'ubo_app/services/090-speech-recognition'
)


def _load_mic_buffer(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Load mic_buffer.py in isolation, returning the module object."""
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())
    spec = importlib.util.spec_from_file_location(
        'mic_buffer_test_module',
        SERVICE_PATH / 'mic_buffer.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _make_sample(data: bytes) -> object:
    """Build a minimal AudioSample stand-in matching the dataclass shape."""
    from ubo_app.store.services.audio import AudioSample

    return AudioSample(data=data, channels=1, rate=16000, width=2)


def test_slugify_handles_phrases_with_spaces_and_punctuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Slug should be lowercase, hyphenated, no leading/trailing separators."""
    mod = _load_mic_buffer(monkeypatch)
    assert mod._slugify("Let's Have a Conversation!") == 'let-s-have-a-conversation'  # noqa: SLF001
    assert mod._slugify('  okay enough  ') == 'okay-enough'  # noqa: SLF001
    assert mod._slugify('can you help me') == 'can-you-help-me'  # noqa: SLF001


def test_slugify_falls_back_for_empty_phrase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pathological inputs must still produce a non-empty filename token."""
    mod = _load_mic_buffer(monkeypatch)
    assert mod._slugify('') == 'phrase'  # noqa: SLF001
    assert mod._slugify('   !!!  ') == 'phrase'  # noqa: SLF001


def test_add_prunes_entries_older_than_window(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """add() must drop samples whose timestamp is older than (latest - window)."""
    mod = _load_mic_buffer(monkeypatch)
    # output_dir isn't touched by add(); use tmp_path just to avoid S108.
    buf = mod.MicBuffer(duration_seconds=5.0, output_dir=tmp_path)

    buf.add(0.0, _make_sample(b'\x00\x00'))
    buf.add(1.0, _make_sample(b'\x01\x00'))
    buf.add(3.0, _make_sample(b'\x02\x00'))
    buf.add(6.0, _make_sample(b'\x03\x00'))

    # Sample at t=0.0 is older than (6.0 - 5.0)=1.0 → pruned.
    # Sample at t=1.0 has t == cutoff (not strictly less) → kept.
    assert [t for t, _ in buf._buffer] == [1.0, 3.0, 6.0]  # noqa: SLF001


def test_dump_writes_wav_with_phrase_slug_and_timestamp(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """dump() writes a valid WAV containing every buffered sample's bytes."""
    mod = _load_mic_buffer(monkeypatch)
    buf = mod.MicBuffer(duration_seconds=5.0, output_dir=tmp_path)

    buf.add(0.0, _make_sample(b'\x01\x00\x02\x00'))
    buf.add(0.5, _make_sample(b'\x03\x00\x04\x00'))

    path = buf.dump("Let's have a conversation")

    assert path is not None
    assert path.parent == tmp_path
    assert path.name.startswith('let-s-have-a-conversation_')
    assert path.suffix == '.wav'
    assert path.exists()

    with wave.open(str(path), 'rb') as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000
        frames = wf.readframes(wf.getnframes())
        # Frames are the concatenation of every buffered sample's data.
        assert frames == b'\x01\x00\x02\x00\x03\x00\x04\x00'


def test_dump_returns_none_when_buffer_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An empty buffer must not write a file or raise."""
    mod = _load_mic_buffer(monkeypatch)
    output_dir = tmp_path / 'wake_phrase_recordings'
    buf = mod.MicBuffer(duration_seconds=5.0, output_dir=output_dir)

    assert buf.dump('okay enough') is None
    # output_dir must not even be created when there's nothing to write.
    assert not output_dir.exists()


def test_dump_creates_output_dir_lazily(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The configured output_dir is created on first dump, not at init."""
    mod = _load_mic_buffer(monkeypatch)
    output_dir = tmp_path / 'wake_phrase_recordings'
    buf = mod.MicBuffer(duration_seconds=5.0, output_dir=output_dir)

    assert not output_dir.exists()  # Lazy.

    buf.add(0.0, _make_sample(b'\x00\x00'))
    path = buf.dump('okay enough')

    assert path is not None
    assert output_dir.is_dir()
    assert path.parent == output_dir
