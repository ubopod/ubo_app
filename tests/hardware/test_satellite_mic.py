"""Closed-loop test: pod speaks, satellite hears, core scores what arrived.

One trial is:

    1. pin output volume and confirm capture is not muted
    2. enable the Asst. Debug session recorder
    3. open a listening session bound to the satellite's ``audio_source``
    4. synthesize a known sentence through the pod's speakers
    5. close the session, then score the recording the core wrote

Both axes are checked. Transcription answers "would the assistant have
understood this"; the signal metrics answer "and if not, why" — level,
alignment, and above all ``duration_ratio``, since audio lost in transit
arrives as a splice and leaves a recording that sounds clean while missing
words.

Thresholds here are intentionally loose. They exist to catch gross failure
until a good run establishes a baseline; tightening them before that would just
manufacture flakiness.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.hardware.audio_metrics import compare_audio, load_wav_mono_16k

if TYPE_CHECKING:
    from immutable import Immutable
    from ubo_bindings.store.v1 import StoreServiceStub

    from tests.hardware.conftest import Satellite

# ~20 unique words, phonetically varied, with short easily-dropped function
# words ("the", "of", "and") whose absence is obvious in a transcript.
SENTENCE = (
    'The quick brown fox jumps over the lazy dog while seven bright '
    'zebras graze beside a calm river and count the golden autumn leaves'
)

SESSIONS_DIR = Path.home() / '.local/share/ubo/assistant_sessions'

# Loose acceptance gates — see module docstring.
MIN_COVERAGE_PCT = 90.0
TEST_OUTPUT_VOLUME = 0.7
MIN_ENVELOPE_CORRELATION = 0.35
MIN_SIMILARITY = 0.5
MIN_KEYWORD_COVERAGE = 0.5
# The speech sits well inside a much longer listening window (chime settling +
# TTS generation), so a large offset is expected and is not a defect.
MAX_REASONABLE_LAG_S = 30.0


async def _dispatch(stub: StoreServiceStub, action: Immutable) -> None:
    """Dispatch a store action over gRPC (same shape as tests/fixtures/dispatch)."""
    from typing import Any, cast

    import ubo_bindings.ubo.v1
    from betterproto.casing import snake_case
    from ubo_bindings.store.v1 import DispatchActionRequest

    from ubo_app.rpc.object_to_message import build_message

    proto_msg = cast('Any', build_message(action))
    field_name = snake_case(type(action).__name__)
    wrapped = ubo_bindings.ubo.v1.Action(**{field_name: proto_msg})
    await stub.dispatch_action(DispatchActionRequest(action=wrapped))


async def _collect_transcript(
    stub: StoreServiceStub,
    action: Immutable,
    *,
    session_id: str,
    timeout_seconds: float = 60.0,
) -> str:
    """Dispatch a transcription request and gather its text frames.

    Subscribes before dispatching so a fast reply cannot be missed, and keys on
    ``session_id`` so a concurrent assistant session's frames are not mistaken
    for ours. Frame handling mirrors ``_SessionCollector`` in
    tools/test_tts_stt_roundtrip.py.
    """
    from ubo_bindings.store.v1 import SubscribeEventRequest
    from ubo_bindings.ubo.v1 import AssistantHandleReportEvent, Event

    parts: list[str] = []
    done = asyncio.Event()

    async def listen() -> None:
        async for response in stub.subscribe_event(
            SubscribeEventRequest(
                events=[Event(assistant_handle_report_event=AssistantHandleReportEvent())],
            ),
        ):
            report = response.event.assistant_handle_report_event
            data = report.data
            group = getattr(data, '_group_current', {})
            field_name = next(iter(group.values()), None)
            if field_name == 'assistance_text_frame':
                frame = data.assistance_text_frame
                if frame.session_id and frame.session_id != session_id:
                    continue
                if frame.text:
                    parts.append(frame.text)
                if frame.is_last_frame:
                    done.set()
                    return
            elif field_name == 'assistance_error_frame':
                done.set()
                return

    listener = asyncio.ensure_future(listen())
    try:
        await asyncio.sleep(0.2)  # let the subscription establish
        await _dispatch(stub, action)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(done.wait(), timeout=timeout_seconds)
    finally:
        listener.cancel()
    return ''.join(parts)


def _playback_volume() -> float:
    """Read the current output volume from the pod's persistent store."""
    state_path = Path.home() / '.config/ubo/state.json'
    try:
        return float(
            json.loads(state_path.read_text()).get('audio_state:playback_volume', -1),
        )
    except (OSError, ValueError):
        return -1.0


def _assistant_debug_enabled() -> bool:
    """Read the live Asst. Debug flag from the pod's real persistent store."""
    state_path = Path.home() / '.config/ubo/state.json'
    try:
        return bool(
            json.loads(state_path.read_text()).get('settings:assistant_debug', False),
        )
    except (OSError, ValueError):
        return False


def _newest_session_dir(after: float) -> Path | None:
    """Most recent session directory created after *after* (epoch seconds)."""
    if not SESSIONS_DIR.exists():
        return None
    candidates = [
        path
        for path in SESSIONS_DIR.iterdir()
        if path.is_dir() and path.stat().st_mtime >= after
    ]
    return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


@pytest.mark.timeout(180)
async def test_satellite_captures_played_sentence(
    satellite: Satellite,
    rpc: StoreServiceStub,
) -> None:
    """The satellite must capture a spoken sentence completely and audibly."""
    import time

    from ubo_app.store.services.assistant import (
        AssistantStartListeningAction,
        AssistantStopListeningAction,
        AssistantSynthesizeAction,
        AssistantTTSName,
        ExternalStopReason,
        KeypadTriggerSource,
    )
    from ubo_app.store.services.audio import (
        AudioDevice,
        AudioSetMuteStatusAction,
        AudioSetVolumeAction,
    )
    from ubo_app.store.services.keypad import Key
    from ubo_app.store.settings.types import SettingsToggleAssistantDebugAction

    started_at = time.time()

    # 1. Pin the acoustic conditions. Volume moves every metric, and capture
    #    mute silently drops AudioReportSampleEvent for *all* sources — an
    #    empty recording that looks exactly like a broken microphone.
    #
    #    Set the volume ONLY when it differs: AudioSetVolumeAction(OUTPUT)
    #    emits Chime.VOLUME_CHANGE, and that chime landing a second before the
    #    sentence was enough to leave the satellite at its noise floor for the
    #    whole session. The harness must not inject sound into the very
    #    acoustic path it is measuring.
    if abs(_playback_volume() - TEST_OUTPUT_VOLUME) > 0.01:
        await _dispatch(
            rpc,
            AudioSetVolumeAction(
                volume=TEST_OUTPUT_VOLUME,
                device=AudioDevice.OUTPUT,
            ),
        )
        await asyncio.sleep(2.0)  # let the chime finish and clear the room
    await _dispatch(
        rpc,
        AudioSetMuteStatusAction(is_mute=False, device=AudioDevice.INPUT),
    )

    # 2. Enable the recorder — only if it is currently off. The action is a
    #    TOGGLE, so dispatching it unconditionally turns the recorder off on
    #    every second run, and the session is silently never written.
    #    The live flag is mirrored to the persistent store on every change, and
    #    that file is the real one (the autouse `_persistent_store` fixture
    #    redirects the library helper at a tmp path, so read it directly).
    if not _assistant_debug_enabled():
        await _dispatch(rpc, SettingsToggleAssistantDebugAction())
        await asyncio.sleep(1.0)
        assert _assistant_debug_enabled(), (
            'Asst. Debug did not turn on; without it no session is recorded'
        )

    # 3. Open a session bound to this satellite. KeypadTriggerSource resolves to
    #    MANUAL turn completion, so silence never ends the turn and *we* own the
    #    stop timing — see silence_user_turn_stop.py.
    await _dispatch(
        rpc,
        AssistantStartListeningAction(
            source=KeypadTriggerSource(key=Key.HOME, mode='hold'),
            audio_source=satellite.audio_source,
        ),
    )
    # Short settle for the satellite's capture path. No longer needs to absorb
    # a chime — the harness no longer makes one (see step 1).
    await asyncio.sleep(2.0)

    # 4. Speak. Piper renders to the pod's speakers; the recorder captures the
    #    same audio as reference.wav, so reference and capture come from one
    #    session and need no separate alignment step.
    await _dispatch(
        rpc,
        AssistantSynthesizeAction(
            text=SENTENCE,
            session_id=uuid.uuid4().hex,
            tts_provider=AssistantTTSName.PIPER,
        ),
    )
    await asyncio.sleep(14.0)

    # 5. Close the session; the recorder writes on the falling edge.
    await _dispatch(
        rpc,
        AssistantStopListeningAction(reason=ExternalStopReason()),
    )
    await asyncio.sleep(2.0)

    directory = _newest_session_dir(started_at)
    assert directory is not None, (
        f'no session directory under {SESSIONS_DIR}. Is Asst. Debug enabled '
        f'and did any audio arrive from {satellite.audio_source}?'
    )

    metadata = json.loads((directory / 'session.json').read_text())
    reference_path = directory / 'reference.wav'
    assert reference_path.exists(), (
        'no reference.wav — nothing was played during the session, so TTS '
        'never reached the speakers'
    )

    captured = load_wav_mono_16k(directory / 'mic.wav')
    reference = load_wav_mono_16k(reference_path)
    result = compare_audio(reference, captured)

    print(f'\nsession: {directory}')  # noqa: T201
    print(f'metrics: {result.summary()}')  # noqa: T201
    print(f'coverage_pct: {metadata["mic"]["coverage_pct"]}')  # noqa: T201
    print(f'gap_ms: {metadata["mic"]["gap_ms"]}')  # noqa: T201
    print(f'mic level: peak={metadata["mic"]["peak_dbfs"]}dBFS '  # noqa: T201
          f'rms={metadata["mic"]["rms_dbfs"]}dBFS')

    # Loss is measured by coverage — audio delivered vs. session wall time —
    # NOT by duration_ratio, which only compares the recording against the
    # reference and is dominated by the listening window being longer than the
    # sentence. Lost samples leave a splice, so coverage is what catches them.
    coverage = metadata['mic']['coverage_pct']
    assert coverage >= MIN_COVERAGE_PCT, (
        f'satellite delivered only {coverage}% of the session as audio — '
        f'samples were dropped in transit, not misheard. '
        f'gaps: {metadata["mic"]["gap_ms"]}'
    )
    assert result.lag_seconds <= MAX_REASONABLE_LAG_S, (
        f'alignment found a {result.lag_seconds:.2f}s lag, beyond plausible '
        f'acoustic latency — the capture probably does not match the reference'
    )
    # Envelope, not raw waveform: across a room, reverb and the independent
    # playback/capture clocks drive raw correlation to ~0 even for a perfect
    # capture. See test_audio_metrics.py for the acoustic-path case.
    assert result.envelope_correlation >= MIN_ENVELOPE_CORRELATION, (
        f'captured audio does not track what was played '
        f'({result.summary()}) — the satellite is not hearing the speaker, '
        f'or is hearing it far too quietly. Worst window: {result.worst_window}'
    )


def _similarity(expected: str, actual: str) -> tuple[float, float]:
    """Return (sequence_ratio, keyword_coverage) between two transcripts.

    Mirrors the scoring already used by tools/test_tts_stt_roundtrip.py so the
    two harnesses stay comparable.
    """
    import difflib
    import re as _re

    def normalise(text: str) -> str:
        return ' '.join(_re.sub(r'[^a-z0-9 ]+', ' ', text.lower()).split())

    expected_norm, actual_norm = normalise(expected), normalise(actual)
    ratio = difflib.SequenceMatcher(None, expected_norm, actual_norm).ratio()

    keywords = {word for word in expected_norm.split() if len(word) >= 4}
    actual_words = set(actual_norm.split())
    coverage = (
        len(keywords & actual_words) / len(keywords) if keywords else 1.0
    )
    return (ratio, coverage)


@pytest.mark.timeout(180)
async def test_satellite_capture_is_intelligible(
    satellite: Satellite,
    rpc: StoreServiceStub,
) -> None:
    """The most recent capture must transcribe close to the spoken sentence.

    Split from the signal test so a failure says which axis broke: audio can be
    complete and still unintelligible (gain-starved, echoey), or intelligible
    despite measurable loss. Transcription goes through the pod's own STT, so
    this measures the recognizer the assistant actually uses.
    """
    import wave

    from ubo_app.store.services.assistant import AssistantTranscribeAction

    directory = _newest_session_dir(0)
    if directory is None:
        pytest.skip('no recorded session available; run the capture test first')

    with wave.open(str(directory / 'mic.wav'), 'rb') as handle:
        pcm = handle.readframes(handle.getnframes())
        rate = handle.getframerate()
        channels = handle.getnchannels()
    assert pcm, 'recorded session contains no audio'

    session_id = uuid.uuid4().hex
    transcript = await _collect_transcript(
        rpc,
        AssistantTranscribeAction(
            audio=pcm,
            session_id=session_id,
            sample_rate=rate,
            num_channels=channels,
        ),
        session_id=session_id,
    )

    print(f'\nsatellite: {satellite.audio_source}')  # noqa: T201
    print(f'expected:   {SENTENCE}')  # noqa: T201
    print(f'transcript: {transcript}')  # noqa: T201

    assert transcript.strip(), (
        'STT returned nothing for the captured audio — it is either silent, '
        "far below the recognizer's level floor, or too damaged to decode"
    )

    ratio, coverage = _similarity(SENTENCE, transcript)
    print(f'similarity: ratio={ratio:.2f} keyword_coverage={coverage:.2f}')  # noqa: T201

    assert ratio >= MIN_SIMILARITY, (
        f'transcript diverges from what was played (ratio {ratio:.2f} < '
        f'{MIN_SIMILARITY}).\n  expected: {SENTENCE}\n  got:      {transcript}'
    )
    assert coverage >= MIN_KEYWORD_COVERAGE, (
        f"only {coverage:.0%} of the sentence's distinctive words survived "
        f'(< {MIN_KEYWORD_COVERAGE:.0%}); words are being lost, not misheard'
    )
