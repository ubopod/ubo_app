"""Per-session assistant audio recorder, gated on the Assistant Debug setting.

Captures, for each listening session, what the assistant actually *received*
from the microphone alongside what the pod *played* while listening, plus a
metadata sidecar. The point is to make satellite-microphone problems
measurable rather than anecdotal: dropped audio arrives as a splice, not as
silence, so it is invisible to listening tests and to naive silence detection,
but obvious in ``coverage_pct`` and the inter-chunk gap distribution recorded
here.

Written under ``DATA_PATH / 'assistant_sessions' / <ISO-ts>-<source>/``:

    mic.wav        the received microphone stream
    reference.wav  audio played out during the session (may be absent)
    session.json   metadata and arrival statistics

Off unless Settings -> System -> General -> Asst. Debug is enabled, because
sessions are written unconditionally while it is on.
"""

from __future__ import annotations

import array
import asyncio
import json
import math
import re
import wave
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from redux import AutorunOptions

from ubo_app.constants import DATA_PATH
from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.audio import (
    AudioPlayAudioSampleEvent,
    AudioPlayAudioSequenceEvent,
    AudioReportSampleEvent,
)
from ubo_app.utils.async_ import create_task

if TYPE_CHECKING:
    from pathlib import Path

SESSIONS_DIR = DATA_PATH / 'assistant_sessions'

# Remote satellites populate only ``sample_speech_recognition`` — the
# native-rate ``sample`` field is left at its default — so the mic track's
# format cannot be read off the incoming samples the way MicBuffer does it. It
# is fixed by the speech-recognition contract instead.
_MIC_RATE = 16000
_MIC_CHANNELS = 1
_MIC_WIDTH = 2

_SLUG_CHARS = re.compile(r'[^a-z0-9]+')

# Satellites buffer audio and dispatch it asynchronously, so the last second or
# two of a session is typically still in flight when listening stops. Writing
# immediately on the falling edge discards it and reports the loss as a capture
# defect. Keep accepting matching audio for this long before writing.
_DRAIN_SECONDS = 3.0


def _slugify(value: str) -> str:
    """Filesystem-safe slug for an audio-source id."""
    return _SLUG_CHARS.sub('-', value.strip().lower()).strip('-') or 'system-mic'


def _percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile of an unsorted list; 0.0 when empty."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(fraction * len(ordered)))
    return ordered[index]


def _dbfs(value: float) -> float:
    """Convert a 0..32768 linear amplitude to dBFS, floored at -120."""
    if value <= 0:
        return -120.0
    return max(-120.0, 20 * math.log10(value / 32768))


def _levels(pcm: bytes) -> tuple[float, float, int]:
    """Return (peak_dbfs, rms_dbfs, clipped_count) for 16-bit mono PCM."""
    if not pcm:
        return (-120.0, -120.0, 0)
    samples = array.array('h')
    samples.frombytes(pcm[: len(pcm) // 2 * 2])
    if not samples:
        return (-120.0, -120.0, 0)
    peak = max(abs(sample) for sample in samples)
    total = sum(float(sample) * sample for sample in samples)
    rms = (total / len(samples)) ** 0.5
    clipped = sum(1 for sample in samples if abs(sample) >= 32000)  # noqa: PLR2004
    return (_dbfs(peak), _dbfs(rms), clipped)


@dataclass
class _Session:
    """Audio and arrival timings accumulated for one listening session."""

    audio_source: str
    started_at: datetime
    closing_at: datetime | None = None
    first_arrival_wall: datetime | None = None
    mic_chunks: list[bytes] = field(default_factory=list)
    arrivals: list[float] = field(default_factory=list)
    reference_chunks: list[bytes] = field(default_factory=list)
    reference_rate: int | None = None
    reference_channels: int | None = None
    reference_width: int | None = None


class AssistantSessionRecorder:
    """Accumulates one listening session's audio and writes it out on stop."""

    def __init__(self) -> None:
        """Start with no session in flight."""
        self._session: _Session | None = None

    @property
    def is_active(self) -> bool:
        """True while a session is being accumulated."""
        return self._session is not None

    # -- ingest ---------------------------------------------------------

    def mark_closing(self) -> None:
        """Record when listening stopped, before the drain window begins."""
        if self._session is not None:
            self._session.closing_at = datetime.now(tz=UTC)

    def start(self, audio_source: str) -> None:
        """Begin accumulating for a new session."""
        self._session = _Session(
            audio_source=audio_source,
            started_at=datetime.now(tz=UTC),
        )

    def add_mic(self, event: AudioReportSampleEvent) -> None:
        """Accumulate a received microphone chunk and its arrival timestamp."""
        session = self._session
        if session is None or event.audio_source != session.audio_source:
            return
        session.mic_chunks.append(event.sample_speech_recognition)
        session.arrivals.append(event.timestamp)
        if session.first_arrival_wall is None:
            session.first_arrival_wall = datetime.now(tz=UTC)

    def add_reference(
        self,
        event: AudioPlayAudioSampleEvent | AudioPlayAudioSequenceEvent,
    ) -> None:
        """Accumulate audio played out while the session is open."""
        session = self._session
        if session is None or event.sample is None:
            return
        session.reference_chunks.append(event.sample.data)
        if session.reference_rate is None:
            session.reference_rate = event.sample.rate
            session.reference_channels = event.sample.channels
            session.reference_width = event.sample.width

    # -- output ---------------------------------------------------------

    def stop(self, stop_reason: str) -> _Session | None:
        """End the session and hand its buffers back for writing."""
        session, self._session = self._session, None
        if session is not None and not session.mic_chunks:
            logger.info(
                'Assistant session recorder: no microphone audio received',
                extra={'audio_source': session.audio_source, 'reason': stop_reason},
            )
        return session

    @staticmethod
    def write(session: _Session, stop_reason: str) -> Path | None:
        """Write mic/reference WAVs and the metadata sidecar. Blocking."""
        # Measured when listening stopped, not when this ran: a drain window
        # runs in between so audio still in flight is not counted as missing.
        stopped_at = session.closing_at or datetime.now(tz=UTC)
        stamp = session.started_at.strftime('%Y-%m-%dT%H%M%S')
        directory = SESSIONS_DIR / f'{stamp}-{_slugify(session.audio_source)}'

        mic_pcm = b''.join(session.mic_chunks)
        wall_duration = (stopped_at - session.started_at).total_seconds()
        # Coverage over the STREAMING window, not the whole session. A
        # core-initiated session opens before the device has been told to start
        # capturing, and that startup latency is not lost audio — counting it
        # as loss made healthy runs read as ~90%. It is reported separately.
        # Measured in core wall-clock from the first chunk that arrived to the
        # moment listening stopped. Using the device's own inter-chunk
        # timestamps instead is biased: N chunks span only N-1 intervals, so a
        # perfectly healthy stream computes as >100%.
        first_wall = session.first_arrival_wall
        startup_latency = (
            (first_wall - session.started_at).total_seconds() if first_wall else 0.0
        )
        stream_span = (
            (stopped_at - first_wall).total_seconds() if first_wall else wall_duration
        )
        audio_seconds = len(mic_pcm) / (_MIC_RATE * _MIC_CHANNELS * _MIC_WIDTH)
        gaps_ms = [
            (later - earlier) * 1000
            for earlier, later in zip(
                session.arrivals,
                session.arrivals[1:],
                strict=False,
            )
        ]
        peak_dbfs, rms_dbfs, clipped = _levels(mic_pcm)

        try:
            directory.mkdir(parents=True, exist_ok=True)
            with wave.open(str(directory / 'mic.wav'), 'wb') as handle:
                handle.setnchannels(_MIC_CHANNELS)
                handle.setsampwidth(_MIC_WIDTH)
                handle.setframerate(_MIC_RATE)
                handle.writeframes(mic_pcm)

            if session.reference_chunks and session.reference_rate:
                with wave.open(str(directory / 'reference.wav'), 'wb') as handle:
                    handle.setnchannels(session.reference_channels or 1)
                    handle.setsampwidth(session.reference_width or 2)
                    handle.setframerate(session.reference_rate)
                    handle.writeframes(b''.join(session.reference_chunks))

            metadata = {
                'audio_source': session.audio_source,
                'stop_reason': stop_reason,
                'started_at': session.started_at.isoformat(),
                'stopped_at': stopped_at.isoformat(),
                'wall_duration_s': round(wall_duration, 3),
                'mic': {
                    'chunks': len(session.mic_chunks),
                    'bytes': len(mic_pcm),
                    'audio_s': round(audio_seconds, 3),
                    # Delivered audio vs. elapsed wall time. Anything well under
                    # 100% means samples were lost, not merely delayed — the
                    # failure mode that sounds like words spliced out.
                    'coverage_pct': round(audio_seconds / stream_span * 100, 1)
                    if stream_span > 0
                    else 0.0,
                    'stream_span_s': round(stream_span, 3),
                    'startup_latency_s': round(startup_latency, 3),
                    'sample_rate': _MIC_RATE,
                    'channels': _MIC_CHANNELS,
                    'gap_ms': {
                        'p50': round(_percentile(gaps_ms, 0.5), 1),
                        'p90': round(_percentile(gaps_ms, 0.9), 1),
                        'max': round(max(gaps_ms), 1) if gaps_ms else 0.0,
                    },
                    'peak_dbfs': round(peak_dbfs, 1),
                    'rms_dbfs': round(rms_dbfs, 1),
                    'clipped_samples': clipped,
                },
                'reference': {
                    'bytes': sum(len(chunk) for chunk in session.reference_chunks),
                    'sample_rate': session.reference_rate,
                    'channels': session.reference_channels,
                },
            }
            (directory / 'session.json').write_text(json.dumps(metadata, indent=2))
        except OSError:
            logger.exception(
                'Assistant session recorder failed to write session',
                extra={'directory': str(directory)},
            )
            return None

        logger.info(
            'Assistant session recorded',
            extra={
                'directory': str(directory),
                'coverage_pct': metadata['mic']['coverage_pct'],
                'audio_s': metadata['mic']['audio_s'],
            },
        )
        return directory


_recorder = AssistantSessionRecorder()

# Identity token for the drain currently in flight, or None when none is.
# `create_task` hands back the `asyncio.Handle` of the *scheduling* call, not
# the task — and the task runs on the service loop while this autorun fires on
# whichever thread dispatched — so an in-flight drain is superseded by
# invalidating its token, never by cancelling it.
_drain_token: object | None = None


def _handle_mic_sample(event: AudioReportSampleEvent) -> None:
    _recorder.add_mic(event)


def _handle_played_sample(
    event: AudioPlayAudioSampleEvent | AudioPlayAudioSequenceEvent,
) -> None:
    _recorder.add_reference(event)


async def _write_session(session: _Session, stop_reason: str) -> None:
    """Write the session off the event loop; WAV writes can be slow."""
    await asyncio.get_running_loop().run_in_executor(
        None,
        AssistantSessionRecorder.write,
        session,
        stop_reason,
    )


async def _finalize_after_drain(stop_reason: str, token: object) -> None:
    """Wait for in-flight audio, then close the session and write it."""
    global _drain_token  # noqa: PLW0603
    await asyncio.sleep(_DRAIN_SECONDS)
    if token is not _drain_token:
        # A new session started during the drain window and took the recorder.
        return
    _drain_token = None
    session = _recorder.stop(stop_reason)
    if session is not None and session.mic_chunks:
        await _write_session(session, stop_reason)


def track_listening(data: tuple[bool, bool, str] | None) -> None:
    """Start / stop the recorder from (debug flag, is_listening, source)."""
    if data is None:
        return
    global _drain_token  # noqa: PLW0603
    enabled, is_listening, audio_source = data
    if enabled and is_listening:
        # A new session during the drain window supersedes it.
        if _drain_token is not None:
            _drain_token = None
            _recorder.stop('superseded')
        # Rising edge — or a session already running when the flag came on,
        # which is recorded from that point rather than skipped.
        if not _recorder.is_active:
            _recorder.start(audio_source)
        return
    if not _recorder.is_active or _drain_token is not None:
        return
    stop_reason = 'listening_ended' if not is_listening else 'debug_disabled'
    _recorder.mark_closing()
    _drain_token = token = object()
    create_task(_finalize_after_drain(stop_reason, token))


def setup_session_recorder() -> None:
    """Subscribe the recorder and drive it from the listening state."""
    store.subscribe_event(AudioReportSampleEvent, _handle_mic_sample)
    store.subscribe_event(AudioPlayAudioSampleEvent, _handle_played_sample)
    store.subscribe_event(AudioPlayAudioSequenceEvent, _handle_played_sample)

    store.autorun(
        lambda state: (
            state.settings.assistant_debug,
            state.assistant.is_listening,
            state.assistant.active_audio_source,
        ),
        options=AutorunOptions(default_value=None),
    )(track_listening)
