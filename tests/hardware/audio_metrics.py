"""Signal-domain comparison of captured audio against a known reference.

Exists because transcription alone cannot tell you *how* audio failed. A
recognizer given quiet audio, clipped audio, or audio with a third of its
samples spliced out will produce similarly-wrong text, and a human listening to
any of them will report "sounds clear but words are missing". These metrics
separate those cases:

``duration_ratio``  how much audio arrived vs. how much was played. Lost
                    samples leave a splice, not silence, so this — not silence
                    detection — is what catches dropped audio.
``envelope_correlation``
                    how well the captured *energy over time* matches the
                    reference. THIS is the acoustic-path metric: raw waveform
                    correlation collapses to ~0 across a room even for a
                    perfect capture, because reverb and the independent
                    playback (48 kHz) and capture (16 kHz) clocks destroy
                    sample-level phase within a second or two. Envelope
                    correlation is immune to all three.
``correlation``     raw waveform correlation. Meaningful only for a digital
                    (non-acoustic) path; kept as a diagnostic.
``lag_seconds``     speaker-to-microphone latency, from the alignment peak.
``peak/rms_dbfs``   capture level, to catch gain-starved or clipping input.
``worst_window``    the least-correlated window, localising *where* it broke.

numpy only — there is deliberately no scipy dependency in this repo.
"""

from __future__ import annotations

import wave
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from pathlib import Path

TARGET_RATE = 16000


@dataclass
class WindowScore:
    """Correlation of one time window, for localising damage."""

    start_seconds: float
    correlation: float


@dataclass
class AudioComparison:
    """Result of comparing a captured recording against its reference."""

    reference_seconds: float
    captured_seconds: float
    duration_ratio: float
    lag_seconds: float
    correlation: float
    envelope_correlation: float
    peak_dbfs: float
    rms_dbfs: float
    clipped_samples: int
    windows: list[WindowScore]

    @property
    def worst_window(self) -> WindowScore | None:
        """The least-correlated window, or None when nothing was compared."""
        return min(self.windows, key=lambda w: w.correlation, default=None)

    def summary(self) -> str:
        """One-line human-readable summary for test output."""
        return (
            f'envelope_corr={self.envelope_correlation:.3f} '
            f'duration_ratio={self.duration_ratio:.3f} '
            f'raw_corr={self.correlation:.3f} '
            f'lag={self.lag_seconds * 1000:.0f}ms '
            f'peak={self.peak_dbfs:.1f}dBFS rms={self.rms_dbfs:.1f}dBFS '
            f'clipped={self.clipped_samples}'
        )


def load_wav_mono_16k(path: Path) -> np.ndarray:
    """Load a WAV as float32 mono at 16 kHz, downmixing and decimating.

    Playback is 48 kHz stereo and capture is 16 kHz mono, so the reference has
    to be brought to the capture's domain before anything can be compared. 48
    to 16 kHz is an exact factor of 3, so a 3-tap box filter before decimation
    is enough to avoid the worst aliasing without pulling in a resampler.
    """
    with wave.open(str(path), 'rb') as handle:
        channels = handle.getnchannels()
        rate = handle.getframerate()
        width = handle.getsampwidth()
        frames = handle.readframes(handle.getnframes())

    if width != 2:
        message = f'only 16-bit PCM is supported, got {width * 8}-bit'
        raise ValueError(message)

    samples = np.frombuffer(frames, dtype='<i2').astype(np.float32)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)

    if rate != TARGET_RATE:
        if rate % TARGET_RATE != 0:
            message = f'cannot decimate {rate} Hz to {TARGET_RATE} Hz by an integer'
            raise ValueError(message)
        factor = rate // TARGET_RATE
        kernel = np.ones(factor, dtype=np.float32) / factor
        samples = np.convolve(samples, kernel, mode='same')[::factor]

    return samples


def _normalised_correlation(left: np.ndarray, right: np.ndarray) -> float:
    """Pearson correlation of two equal-length signals; 0.0 if either is flat."""
    if len(left) == 0 or len(right) == 0:
        return 0.0
    left = left - left.mean()
    right = right - right.mean()
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denominator == 0:
        return 0.0
    return float(np.dot(left, right) / denominator)


def _best_lag(reference: np.ndarray, captured: np.ndarray) -> int:
    """Sample offset of *captured* relative to *reference*, via FFT correlation.

    Done in the frequency domain because a direct correlation over several
    seconds at 16 kHz is quadratic and takes minutes.
    """
    size = 1 << int(np.ceil(np.log2(len(reference) + len(captured))))
    spectrum = np.fft.rfft(captured, size) * np.conj(np.fft.rfft(reference, size))
    correlation = np.fft.irfft(spectrum, size)
    # Only non-negative lags are physical: the microphone cannot hear the
    # speaker before it plays.
    return int(np.argmax(correlation[: max(1, len(correlation) // 2)]))


_ENVELOPE_FRAME_SECONDS = 0.02


def _envelope(samples: np.ndarray) -> np.ndarray:
    """Per-frame RMS energy — the shape of the sound, without its phase."""
    frame = int(_ENVELOPE_FRAME_SECONDS * TARGET_RATE)
    count = len(samples) // frame
    if count == 0:
        return np.zeros(0, dtype=np.float32)
    frames = samples[: count * frame].reshape(count, frame)
    return np.sqrt(np.mean(np.square(frames), axis=1) + 1e-9)


def _envelope_correlation(reference: np.ndarray, captured: np.ndarray) -> float:
    """Best envelope correlation between two signals, aligning on energy.

    Aligned independently of the waveform lag: across an acoustic path the
    waveform peak is noise, so its "best" offset is meaningless.
    """
    ref_env, cap_env = _envelope(reference), _envelope(captured)
    if len(ref_env) < 2 or len(cap_env) < 2:
        return 0.0
    ref_n = (ref_env - ref_env.mean()) / (ref_env.std() or 1)
    cap_n = (cap_env - cap_env.mean()) / (cap_env.std() or 1)
    size = 1 << int(np.ceil(np.log2(len(ref_n) + len(cap_n))))
    correlation = np.fft.irfft(
        np.fft.rfft(cap_n, size) * np.conj(np.fft.rfft(ref_n, size)),
        size,
    )
    lag = int(np.argmax(correlation[: max(1, len(correlation) // 2)]))
    window = cap_n[lag : lag + len(ref_n)]
    overlap = min(len(window), len(ref_n))
    return _normalised_correlation(ref_n[:overlap], window[:overlap])


def _levels(samples: np.ndarray) -> tuple[float, float, int]:
    """Return (peak_dbfs, rms_dbfs, clipped_count)."""
    if len(samples) == 0:
        return (-120.0, -120.0, 0)
    peak = float(np.max(np.abs(samples)))
    rms = float(np.sqrt(np.mean(np.square(samples))))
    clipped = int(np.count_nonzero(np.abs(samples) >= 32000))

    def to_dbfs(value: float) -> float:
        return max(-120.0, 20 * float(np.log10(value / 32768))) if value > 0 else -120.0

    return (to_dbfs(peak), to_dbfs(rms), clipped)


def compare_audio(
    reference: np.ndarray,
    captured: np.ndarray,
    *,
    window_seconds: float = 0.2,
) -> AudioComparison:
    """Compare a captured recording against its reference signal."""
    reference_seconds = len(reference) / TARGET_RATE
    captured_seconds = len(captured) / TARGET_RATE
    peak_dbfs, rms_dbfs, clipped = _levels(captured)

    lag = _best_lag(reference, captured) if len(reference) and len(captured) else 0
    aligned = captured[lag:] if lag < len(captured) else np.array([], dtype=np.float32)
    overlap = min(len(aligned), len(reference))
    correlation = _normalised_correlation(reference[:overlap], aligned[:overlap])

    window = int(window_seconds * TARGET_RATE)
    windows = [
        WindowScore(
            start_seconds=start / TARGET_RATE,
            correlation=_normalised_correlation(
                reference[start : start + window],
                aligned[start : start + window],
            ),
        )
        for start in range(0, max(0, overlap - window), window)
    ]

    return AudioComparison(
        reference_seconds=reference_seconds,
        captured_seconds=captured_seconds,
        duration_ratio=(
            captured_seconds / reference_seconds if reference_seconds else 0.0
        ),
        lag_seconds=lag / TARGET_RATE,
        correlation=correlation,
        envelope_correlation=_envelope_correlation(reference, captured),
        peak_dbfs=peak_dbfs,
        rms_dbfs=rms_dbfs,
        clipped_samples=clipped,
        windows=windows,
    )
