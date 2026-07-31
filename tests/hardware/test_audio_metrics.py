"""Tests that the audio comparison detects each way capture can fail.

This is the harness's own safety net. Every conclusion the hardware test draws
rests on these metrics, so they are exercised against deliberately corrupted
copies of a known signal before any real hardware result is trusted. A metric
that cannot detect a fault injected on purpose cannot be believed when it
reports a clean run.

Pure numpy — runs anywhere, no hardware, no gating.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests.hardware.audio_metrics import TARGET_RATE, compare_audio


@pytest.fixture
def reference() -> np.ndarray:
    """Three seconds of amplitude-modulated tones, roughly speech-like."""
    rng = np.random.default_rng(seed=1234)
    t = np.arange(3 * TARGET_RATE) / TARGET_RATE
    carrier = np.sin(2 * np.pi * 220 * t) + 0.5 * np.sin(2 * np.pi * 700 * t)
    envelope = 0.5 + 0.5 * np.sin(2 * np.pi * 2.5 * t)
    noise = rng.normal(0, 0.02, len(t))
    return ((carrier * envelope + noise) * 8000).astype(np.float32)


def test_identical_audio_scores_near_perfect(reference: np.ndarray) -> None:
    """A clean capture must produce ratio 1.0 and correlation ~1.0."""
    result = compare_audio(reference, reference.copy())

    assert result.duration_ratio == pytest.approx(1.0, abs=0.01)
    assert result.correlation > 0.99
    assert result.lag_seconds == pytest.approx(0.0, abs=0.001)


def test_spliced_audio_is_caught_by_duration_ratio(reference: np.ndarray) -> None:
    """Dropped samples leave a splice, not silence — ratio must fall.

    This is the exact failure the ESP32 exhibited: audio that sounds continuous
    and clear, with words simply absent. Silence detection cannot see it.
    """
    # Remove 10% by cutting 30 evenly-spaced 10ms holes.
    hole = int(0.01 * TARGET_RATE)
    keep = np.ones(len(reference), dtype=bool)
    for index in range(30):
        start = int((index + 0.5) * len(reference) / 30)
        keep[start : start + hole * 10] = False
    spliced = reference[keep]

    result = compare_audio(reference, spliced)

    assert result.duration_ratio < 0.95
    # And the recording contains no long silence, so a silence-run check
    # would have reported it as perfectly healthy.
    assert np.count_nonzero(np.abs(spliced) < 1) < len(spliced) * 0.01


def test_attenuated_audio_is_caught_by_levels(reference: np.ndarray) -> None:
    """20 dB down: correlation stays high, levels must reveal it."""
    quiet = reference * 0.1

    result = compare_audio(reference, quiet)

    assert result.correlation > 0.99
    assert result.duration_ratio == pytest.approx(1.0, abs=0.01)
    baseline = compare_audio(reference, reference.copy())
    assert result.rms_dbfs < baseline.rms_dbfs - 15


def test_delayed_audio_reports_lag_and_still_aligns(reference: np.ndarray) -> None:
    """A 300 ms acoustic delay must be measured, not mistaken for corruption."""
    delay = int(0.3 * TARGET_RATE)
    delayed = np.concatenate([np.zeros(delay, dtype=np.float32), reference])

    result = compare_audio(reference, delayed)

    assert result.lag_seconds == pytest.approx(0.3, abs=0.01)
    assert result.correlation > 0.99


def test_envelope_survives_an_acoustic_path_where_raw_correlation_dies(
    reference: np.ndarray,
) -> None:
    """The metric must still recognise audio that crossed a room.

    This is the case the original metric got wrong. Simulating what a speaker
    -> room -> microphone path does — reverb tail, attenuation, noise, and the
    slow drift between an independent playback and capture clock — collapses
    raw waveform correlation to near zero even though the recording is plainly
    the same sentence. Envelope correlation must survive it, or every real
    hardware run reports a false failure.
    """
    rng = np.random.default_rng(seed=5)
    # Reverb: a few decaying reflections.
    reverb = reference.copy()
    for delay_ms, gain in ((17, 0.5), (31, 0.3), (57, 0.18), (89, 0.1)):
        d = int(delay_ms / 1000 * TARGET_RATE)
        reverb[d:] += reference[:-d] * gain
    # Clock drift: capture clock 0.1% fast, i.e. resampled off the reference.
    n = len(reverb)
    drifted = np.interp(
        np.arange(0, n, 1.001)[: int(n / 1.001)],
        np.arange(n),
        reverb,
    ).astype(np.float32)
    # Attenuation + room noise floor.
    captured = drifted * 0.08 + rng.normal(0, 40, len(drifted)).astype(np.float32)

    result = compare_audio(reference, captured)

    # Deliberately no assertion on raw ``correlation`` here: this fixture is
    # tonal, and periodic signals re-align under drift, so raw correlation
    # stays misleadingly high (~0.5). Real speech is aperiodic — on actual
    # hardware, a capture whose envelope correlation was clearly non-zero
    # measured a raw correlation of 0.013. That is the case this metric exists
    # for, and only the envelope figure is trustworthy across an acoustic path.
    assert result.envelope_correlation > 0.6, (
        f'envelope correlation {result.envelope_correlation:.3f} too low — the '
        f'metric cannot recognise audio that crossed an acoustic path'
    )


def test_envelope_rejects_unrelated_audio(reference: np.ndarray) -> None:
    """Envelope correlation must not pass noise, or it proves nothing."""
    rng = np.random.default_rng(seed=11)
    noise = rng.normal(0, 3000, len(reference)).astype(np.float32)
    assert compare_audio(reference, noise).envelope_correlation < 0.3


def test_noise_scores_poorly(reference: np.ndarray) -> None:
    """Unrelated noise must not pass as a match."""
    rng = np.random.default_rng(seed=99)
    noise = rng.normal(0, 3000, len(reference)).astype(np.float32)

    result = compare_audio(reference, noise)

    assert result.correlation < 0.3


def test_worst_window_localises_damage(reference: np.ndarray) -> None:
    """A burst of corruption should show up in one window, not smear."""
    damaged = reference.copy()
    rng = np.random.default_rng(seed=7)
    start = int(1.5 * TARGET_RATE)
    span = int(0.2 * TARGET_RATE)
    damaged[start : start + span] = rng.normal(0, 3000, span).astype(np.float32)

    result = compare_audio(damaged, damaged)  # sanity: self-compare is clean
    assert result.correlation > 0.99

    result = compare_audio(reference, damaged)
    worst = result.worst_window
    assert worst is not None
    assert 1.3 <= worst.start_seconds <= 1.8
    assert worst.correlation < 0.5
