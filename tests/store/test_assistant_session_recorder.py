"""Tests for the per-session assistant audio recorder.

Loads ``session_recorder.py`` in isolation (same approach as
``test_mic_buffer.py``) so the test does not drag in the assistant service's
heavy engine imports.

The behaviour worth pinning down here is the part that is easy to get wrong and
invisible when wrong: the microphone WAV must be written at 16 kHz mono
regardless of what the sender did or didn't populate, audio from a different
``audio_source`` must be ignored entirely, and ``coverage_pct`` must actually
fall when samples go missing — dropped audio arrives as a splice, so a recording
that lost a third of its samples still *sounds* plausible and still passes any
silence-based check.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import wave
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from types import ModuleType

    import pytest


SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/090-assistant'


def _load_recorder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    """Load session_recorder.py in isolation, pointed at a temp output dir."""
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())
    spec = importlib.util.spec_from_file_location(
        'assistant_session_recorder_test_module',
        SERVICE_PATH / 'session_recorder.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    # Redirect output away from the real data dir. Set through the module's
    # namespace rather than as an attribute so pyright doesn't object to
    # assigning an unknown attribute on ModuleType.
    module.__dict__['SESSIONS_DIR'] = tmp_path / 'assistant_sessions'
    return module


class _FakeMicEvent:
    """Minimal stand-in for AudioReportSampleEvent."""

    def __init__(self, data: bytes, timestamp: float, audio_source: str) -> None:
        self.sample_speech_recognition = data
        self.timestamp = timestamp
        self.audio_source = audio_source


def _silence(seconds: float) -> bytes:
    """16 kHz mono 16-bit silence of the given duration."""
    return b'\x00\x00' * int(16000 * seconds)


def test_mic_wav_is_16khz_mono_regardless_of_sender(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Satellites never set the native-rate `sample`; the header is fixed."""
    mod = _load_recorder(monkeypatch, tmp_path)
    recorder = mod.AssistantSessionRecorder()
    recorder.start('esp32:aabbccddeeff')
    recorder.add_mic(_FakeMicEvent(_silence(0.2), 1.0, 'esp32:aabbccddeeff'))
    session = recorder.stop('listening_ended')
    assert session is not None

    directory = mod.AssistantSessionRecorder.write(session, 'listening_ended')
    assert directory is not None

    with wave.open(str(directory / 'mic.wav'), 'rb') as handle:
        assert handle.getframerate() == 16000
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2


def test_audio_from_another_source_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A session bound to one satellite must not record the system mic."""
    mod = _load_recorder(monkeypatch, tmp_path)
    recorder = mod.AssistantSessionRecorder()
    recorder.start('esp32:aabbccddeeff')
    recorder.add_mic(_FakeMicEvent(_silence(0.2), 1.0, ''))
    recorder.add_mic(_FakeMicEvent(_silence(0.2), 1.2, 'web-ui:other'))
    session = recorder.stop('listening_ended')

    assert session is not None
    assert session.mic_chunks == []


def test_coverage_pct_detects_missing_audio(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Lost samples leave a splice, not silence — coverage is what catches it."""
    mod = _load_recorder(monkeypatch, tmp_path)
    from datetime import UTC, datetime, timedelta

    # Two seconds of streaming, but only ~1s of audio delivered: the sender
    # dropped half. The recording still sounds like continuous speech.
    recorder = mod.AssistantSessionRecorder()
    recorder.start('esp32:aabbccddeeff')
    session = recorder._session  # noqa: SLF001
    assert session is not None
    now = datetime.now(tz=UTC)
    session.started_at = now - timedelta(seconds=3)
    for index in range(5):
        recorder.add_mic(
            _FakeMicEvent(_silence(0.2), 1.0 + index * 0.4, 'esp32:aabbccddeeff'),
        )
    # Streaming began 1s after the session opened and ran for 2s.
    session.first_arrival_wall = now - timedelta(seconds=2)
    recorder.mark_closing()
    stopped = recorder.stop('listening_ended')
    assert stopped is not None

    directory = mod.AssistantSessionRecorder.write(stopped, 'listening_ended')
    assert directory is not None
    metadata = json.loads((directory / 'session.json').read_text())

    assert metadata['mic']['audio_s'] == 1.0
    # 1s of audio across a 2s streaming window.
    assert 45 <= metadata['mic']['coverage_pct'] <= 55
    # Chunks arrived every 400ms carrying only 200ms of audio each.
    assert metadata['mic']['gap_ms']['p50'] > 300
    # The 1s before streaming started is reported separately, not as loss.
    assert 0.5 <= metadata['mic']['startup_latency_s'] <= 1.5


def test_full_coverage_session_reports_100_percent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A healthy session must not trip the coverage check.

    Includes startup latency, which a core-initiated session always has: the
    device is told to start only after the session opens. Counting that as loss
    made healthy runs read as ~90%.
    """
    mod = _load_recorder(monkeypatch, tmp_path)
    from datetime import UTC, datetime, timedelta

    recorder = mod.AssistantSessionRecorder()
    recorder.start('esp32:aabbccddeeff')
    session = recorder._session  # noqa: SLF001
    assert session is not None
    now = datetime.now(tz=UTC)
    session.started_at = now - timedelta(seconds=3)
    for index in range(5):
        recorder.add_mic(
            _FakeMicEvent(_silence(0.2), 1.0 + index * 0.2, 'esp32:aabbccddeeff'),
        )
    session.first_arrival_wall = now - timedelta(seconds=1)
    recorder.mark_closing()
    stopped = recorder.stop('listening_ended')
    assert stopped is not None

    directory = mod.AssistantSessionRecorder.write(stopped, 'listening_ended')
    assert directory is not None
    metadata = json.loads((directory / 'session.json').read_text())
    assert metadata['mic']['coverage_pct'] >= 95


class _FakeHandle:
    """What ``create_task`` really hands back: an ``asyncio.Handle``.

    It schedules the coroutine on the service loop via ``call_soon_threadsafe``
    and returns that call's handle, so the object has ``cancel``/``cancelled``
    and — the part that matters here — no ``done``.
    """

    def cancel(self) -> None:
        """Cancel the scheduling callback, not the task it would create."""

    def cancelled(self) -> bool:
        """Whether the scheduling callback was cancelled."""
        return False


def _stub_create_task(
    monkeypatch: pytest.MonkeyPatch,
    mod: ModuleType,
) -> list[Coroutine[None, None, None]]:
    """Capture scheduled coroutines, returning a handle shaped like the real one."""
    scheduled: list[Coroutine[None, None, None]] = []

    def create_task(
        coroutine: Coroutine[None, None, None],
        *_args: object,
        **_kwargs: object,
    ) -> _FakeHandle:
        scheduled.append(coroutine)
        return _FakeHandle()

    monkeypatch.setitem(mod.__dict__, 'create_task', create_task)
    return scheduled


def test_back_to_back_sessions_do_not_trip_over_the_drain_handle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A second session must not blow up on the first one's drain bookkeeping.

    ``create_task`` returns the ``asyncio.Handle`` of the *scheduling* call, not
    a ``Task``, so anything that treated the stored value as a task (``.done()``,
    ``.cancel()``) raised ``AttributeError`` on the second session — the first
    one always worked, which is what hid it.
    """
    mod = _load_recorder(monkeypatch, tmp_path)
    scheduled = _stub_create_task(monkeypatch, mod)

    mod.track_listening((True, True, 'esp32:aabbccddeeff'))
    assert mod._recorder.is_active  # noqa: SLF001

    mod.track_listening((True, False, 'esp32:aabbccddeeff'))
    assert len(scheduled) == 1

    # Second session, while the first one's drain is still notionally in flight.
    mod.track_listening((True, True, 'esp32:aabbccddeeff'))
    assert mod._recorder.is_active  # noqa: SLF001


async def test_a_superseded_drain_leaves_the_new_session_alone(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The drain that lost the race must not stop the session that replaced it.

    Both drains run to completion — the loser can only be told it is stale, not
    cancelled, because the task lives on the service loop while the autorun
    fires on whichever thread dispatched it.
    """
    mod = _load_recorder(monkeypatch, tmp_path)
    scheduled = _stub_create_task(monkeypatch, mod)
    monkeypatch.setitem(mod.__dict__, '_DRAIN_SECONDS', 0)

    mod.track_listening((True, True, 'esp32:aabbccddeeff'))
    mod.track_listening((True, False, 'esp32:aabbccddeeff'))
    mod.track_listening((True, True, 'esp32:aabbccddeeff'))

    # The superseded drain now runs; it must not take the live session with it.
    await scheduled[0]

    assert mod._recorder.is_active  # noqa: SLF001
