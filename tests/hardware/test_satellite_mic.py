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
from tests.hardware.conftest import GRPC_HOST, GRPC_PORT

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
TALK_WINDOW_SECONDS = 24.0
# How much worse the captured transcript may score than the same STT engine on
# the reference audio. Absolute similarity conflates capture quality with TTS
# pronunciation and STT quirks; the delta isolates what the air path cost.
MAX_SIMILARITY_DROP = 0.20
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
    action_audio: bytes,
    *,
    sample_rate: int,
    num_channels: int,
    timeout_seconds: float = 90.0,
) -> str:
    """Transcribe audio with the pod's own STT and return the text.

    Uses ``UboRPCClient`` rather than the raw stub: it owns its event loop and
    hands back a real unsubscribe callable. Driving a streaming subscription
    directly from the test's loop left the stream open at teardown and hung the
    run until the shell timeout killed it, before pytest could report anything.

    Signalling is a ``threading.Event``, not ``asyncio.Event`` — the callback
    fires on the client's loop, and asyncio primitives are not safe to set
    across loops.
    """
    import threading

    from ubo_bindings.client import UboRPCClient
    from ubo_bindings.ubo.v1 import (
        Action,
        AssistantHandleReportEvent,
        AssistantTranscribeAction,
        Event,
    )

    session_id = uuid.uuid4().hex
    parts: list[str] = []
    done = threading.Event()

    def on_report(event: Event) -> None:
        report = event.assistant_handle_report_event
        if not report:
            return
        # session_id lives on the inner Assistance*Frame, not on the oneof
        # wrapper — keying on the wrapper silently matches nothing.
        group = getattr(report.data, '_group_current', {})
        field_name = next(iter(group.values()), None)
        if field_name is None:
            return
        inner = getattr(report.data, field_name)
        if getattr(inner, 'session_id', '') != session_id:
            return
        if field_name == 'assistance_text_frame':
            if inner.text:
                parts.append(inner.text)
            if inner.is_last_frame:
                done.set()
        elif field_name == 'assistance_error_frame':
            done.set()

    client = UboRPCClient(GRPC_HOST, GRPC_PORT)
    unsubscribe = client.subscribe_event(
        event_type=Event(assistant_handle_report_event=AssistantHandleReportEvent()),
        callback=on_report,
    )
    try:
        await asyncio.sleep(0.5)  # let the subscription establish
        client.dispatch(
            action=Action(
                assistant_transcribe_action=AssistantTranscribeAction(
                    audio=action_audio,
                    session_id=session_id,
                    sample_rate=sample_rate,
                    num_channels=num_channels,
                ),
            ),
        )
        # Polling a threading.Event, deliberately: an asyncio.Event cannot be
        # set safely from the client's own loop (see the docstring).
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while not done.is_set() and asyncio.get_running_loop().time() < deadline:  # noqa: ASYNC110
            await asyncio.sleep(0.25)
    finally:
        with contextlib.suppress(Exception):
            unsubscribe()
        with contextlib.suppress(Exception):
            client.close()
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
    # Piper has to synthesize before anything plays, and the sentence itself
    # runs ~8s. Stopping at 14s clipped the final word. Generous tail: the extra
    # silence costs nothing (loss is gated on coverage, and the envelope
    # comparison only spans the reference's length).
    await asyncio.sleep(TALK_WINDOW_SECONDS)

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
    rpc: StoreServiceStub,  # noqa: ARG001  (ensures the core is reachable)
) -> None:
    """The most recent capture must transcribe close to the spoken sentence.

    Split from the signal test so a failure says which axis broke: audio can be
    complete and still unintelligible (gain-starved, echoey), or intelligible
    despite measurable loss. Transcription goes through the pod's own STT, so
    this measures the recognizer the assistant actually uses.
    """
    import wave

    directory = _newest_session_dir(0)
    if directory is None:
        pytest.skip('no recorded session available; run the capture test first')

    with wave.open(str(directory / 'mic.wav'), 'rb') as handle:
        pcm = handle.readframes(handle.getnframes())
        rate = handle.getframerate()
        channels = handle.getnchannels()
    assert pcm, 'recorded session contains no audio'

    transcript = await _collect_transcript(
        pcm,
        sample_rate=rate,
        num_channels=channels,
    )

    # Control: the same STT engine on the audio that was PLAYED. Anything it
    # drops here (TTS pronunciation, engine quirks) is not the microphone's
    # fault, and scoring the capture against the literal sentence would blame
    # the air path for it.
    reference_transcript = ''
    reference_path = directory / 'reference.wav'
    if reference_path.exists():
        with wave.open(str(reference_path), 'rb') as handle:
            reference_transcript = await _collect_transcript(
                handle.readframes(handle.getnframes()),
                sample_rate=handle.getframerate(),
                num_channels=handle.getnchannels(),
            )

    print(f'\nsatellite:  {satellite.audio_source}')  # noqa: T201
    print(f'expected:   {SENTENCE}')  # noqa: T201
    print(f'reference:  {reference_transcript}')  # noqa: T201
    print(f'captured:   {transcript}')  # noqa: T201

    assert transcript.strip(), (
        'STT returned nothing for the captured audio — it is either silent, '
        "far below the recognizer's level floor, or too damaged to decode"
    )

    ratio, coverage = _similarity(SENTENCE, transcript)
    print(f'captured vs sentence: ratio={ratio:.2f} coverage={coverage:.2f}')  # noqa: T201

    assert ratio >= MIN_SIMILARITY, (
        f'transcript diverges from what was played (ratio {ratio:.2f} < '
        f'{MIN_SIMILARITY}).\n  expected: {SENTENCE}\n  got:      {transcript}'
    )
    assert coverage >= MIN_KEYWORD_COVERAGE, (
        f"only {coverage:.0%} of the sentence's distinctive words survived "
        f'(< {MIN_KEYWORD_COVERAGE:.0%}); words are being lost, not misheard'
    )

    if reference_transcript:
        reference_ratio, _ = _similarity(SENTENCE, reference_transcript)
        print(  # noqa: T201
            f'reference vs sentence: ratio={reference_ratio:.2f} '
            f'-> air-path cost {reference_ratio - ratio:+.2f}',
        )
        # The delta, not the absolute score, is what the microphone path cost:
        # anything the same engine also drops on the played audio is a TTS or
        # STT trait, and blaming the air path for it would be wrong.
        assert ratio >= reference_ratio - MAX_SIMILARITY_DROP, (
            f'capture lost {reference_ratio - ratio:.2f} of transcription '
            f'accuracy versus the same engine on the played audio '
            f'({ratio:.2f} vs {reference_ratio:.2f}) — that gap is what the '
            f'microphone path cost, and it is too large'
        )
