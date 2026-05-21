# ruff: noqa
"""Disposable end-to-end test: TTS -> STT round-trip over gRPC.

Boots the ubo app, waits for the assistant service to come up, then:

  1. sends a sentence to the TTS engine (Piper) and collects the synthesized audio,
  2. feeds that audio to the STT engine (Vosk) and collects the transcription,
  3. fuzzy-compares + keyword-matches the transcription against the original text.

This is a standalone scratch script — NOT wired into the pytest suite or any test
fixtures. Run it from the repo root:

    uv run python tools/test_tts_stt_roundtrip.py

Exit code 0 = pass, 1 = fail. The app's output is teed to ./ubo-app-roundtrip.log
and the synthesized audio is written to /tmp/ubo-roundtrip-tts.wav for inspection.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import re
import signal
import socket
import subprocess
import sys
import time
import uuid
import wave
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from ubo_bindings.client import UboRPCClient
from ubo_bindings.ubo.v1 import (
    Action,
    AssistantHandleReportEvent,
    AssistantSttName,
    AssistantSynthesizeAction,
    AssistantTranscribeAction,
    AssistantTtsName,
    Event,
)

logger = logging.getLogger('roundtrip')

# --- configuration -----------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
LAUNCH_COMMAND = ['uv', 'run', 'ubo']
GRPC_HOST = os.environ.get('UBO_GRPC_LISTEN_ADDRESS', '127.0.0.1')
GRPC_PORT = int(os.environ.get('UBO_GRPC_LISTEN_PORT', '50051'))

TEST_SENTENCE = 'the quick brown fox jumps over the lazy dog'

# Local providers — no API keys needed.
TTS_PROVIDER = AssistantTtsName.PIPER
STT_PROVIDER = AssistantSttName.VOSK

GRPC_UP_TIMEOUT = 120.0  # seconds to wait for the core gRPC server
ASSISTANT_UP_BUDGET = 240.0  # total seconds to keep retrying for the assistant
SYNTHESIS_TIMEOUT = 45.0  # per-attempt seconds to wait for TTS output
TRANSCRIPTION_TIMEOUT = 60.0  # seconds to wait for STT output

APP_LOG_PATH = REPO_ROOT / 'ubo-app-roundtrip.log'
TTS_WAV_PATH = Path('/tmp/ubo-roundtrip-tts.wav')  # noqa: S108

# Pass thresholds — STT is lossy, so be lenient and lean on keyword coverage.
MIN_SIMILARITY_RATIO = 0.6
MIN_KEYWORD_COVERAGE = 0.5
_KEYWORD_MIN_LEN = 4


# --- app lifecycle -----------------------------------------------------------
def launch_app() -> subprocess.Popen:
    """Launch the ubo app headless, teeing its output to a log file."""
    env = os.environ.copy()
    env['HEADLESS_KIVY_DEBUG'] = 'true'
    env['KIVY_NO_ARGS'] = '1'
    env['KIVY_NO_CONFIG'] = '1'
    env['KIVY_NO_FILELOG'] = '1'
    env['KIVY_NO_CONSOLELOG'] = '1'
    # Let `uv run` resolve each subprocess' own venv.
    env.pop('VIRTUAL_ENV', None)
    env.pop('UV_PROJECT_ENVIRONMENT', None)

    logger.info('Launching app: %s (logs -> %s)', ' '.join(LAUNCH_COMMAND), APP_LOG_PATH)
    log_file = APP_LOG_PATH.open('wb')
    return subprocess.Popen(  # noqa: S603
        LAUNCH_COMMAND,
        cwd=REPO_ROOT,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def terminate_app(process: subprocess.Popen) -> None:
    """Stop the app and best-effort clean up the assistant subprocess."""
    logger.info('Stopping the app (pid=%d)', process.pid)
    with contextlib.suppress(ProcessLookupError):
        process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    # The assistant subprocess starts its own session — kill any stragglers.
    with contextlib.suppress(Exception):
        subprocess.run(['pkill', '-f', 'ubo-assistant'], check=False)  # noqa: S603, S607


def wait_for_grpc(host: str, port: int, timeout: float) -> bool:
    """Block until the gRPC TCP port accepts connections, or the timeout elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with contextlib.suppress(OSError), socket.create_connection((host, port), timeout=2):
            return True
        time.sleep(1.0)
    return False


# --- frame collection --------------------------------------------------------
def _active_field(data: object) -> str | None:
    """Return the active oneof field name of an AcceptableAssistanceFrame."""
    group = getattr(data, '_group_current', {})
    return next(iter(group.values()), None)


@dataclass
class _SessionCollector:
    """Accumulates report frames for a single request session_id."""

    session_id: str
    done: asyncio.Event
    audio: bytearray = field(default_factory=bytearray)
    sample_rate: int = 0
    num_channels: int = 1
    text_parts: list[str] = field(default_factory=list)
    error: str | None = None

    def handle(self, data: object) -> None:
        """Process one report frame addressed to this session."""
        field_name = _active_field(data)
        if field_name == 'assistance_audio_frame':
            frame = data.assistance_audio_frame  # type: ignore[attr-defined]
            if frame.audio and frame.audio.data:
                self.audio.extend(frame.audio.data)
                self.sample_rate = frame.audio.rate or self.sample_rate
                self.num_channels = frame.audio.channels or self.num_channels
            if frame.is_last_frame:
                self.done.set()
        elif field_name == 'assistance_text_frame':
            frame = data.assistance_text_frame  # type: ignore[attr-defined]
            if frame.text:
                self.text_parts.append(frame.text)
            if frame.is_last_frame:
                self.done.set()
        elif field_name == 'assistance_error_frame':
            frame = data.assistance_error_frame  # type: ignore[attr-defined]
            self.error = frame.error
            self.done.set()


async def _synthesize(client: UboRPCClient, collector: _SessionCollector) -> None:
    """Dispatch a TTS request and wait for the synthesized audio."""
    client.dispatch(
        action=Action(
            assistant_synthesize_action=AssistantSynthesizeAction(
                text=TEST_SENTENCE,
                session_id=collector.session_id,
                tts_provider=TTS_PROVIDER,
            ),
        ),
    )
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(collector.done.wait(), timeout=SYNTHESIS_TIMEOUT)


async def _transcribe(
    client: UboRPCClient,
    collector: _SessionCollector,
    audio: bytes,
    sample_rate: int,
    num_channels: int,
) -> None:
    """Dispatch an STT request for the given audio and wait for the transcription."""
    client.dispatch(
        action=Action(
            assistant_transcribe_action=AssistantTranscribeAction(
                audio=audio,
                session_id=collector.session_id,
                sample_rate=sample_rate,
                num_channels=num_channels,
                stt_provider=STT_PROVIDER,
            ),
        ),
    )
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(collector.done.wait(), timeout=TRANSCRIPTION_TIMEOUT)


# --- comparison --------------------------------------------------------------
def _normalize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split into words."""
    return re.sub(r'[^a-z0-9 ]', ' ', text.lower()).split()


def compare(original: str, transcribed: str) -> tuple[float, float, bool]:
    """Return (similarity_ratio, keyword_coverage, passed)."""
    original_words = _normalize(original)
    transcribed_words = _normalize(transcribed)

    ratio = SequenceMatcher(
        None,
        ' '.join(original_words),
        ' '.join(transcribed_words),
    ).ratio()

    keywords = [w for w in original_words if len(w) >= _KEYWORD_MIN_LEN]
    transcribed_set = set(transcribed_words)
    matched = [w for w in keywords if w in transcribed_set]
    coverage = len(matched) / len(keywords) if keywords else 1.0

    passed = ratio >= MIN_SIMILARITY_RATIO or coverage >= MIN_KEYWORD_COVERAGE
    return ratio, coverage, passed


def _write_wav(path: Path, pcm: bytes, sample_rate: int, num_channels: int) -> None:
    """Write 16-bit PCM to a WAV file for manual inspection."""
    with wave.open(str(path), 'wb') as wav:
        wav.setnchannels(num_channels or 1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate or 16000)
        wav.writeframes(pcm)


# --- orchestration -----------------------------------------------------------
async def _round_trip(client: UboRPCClient) -> bool:
    """Run the TTS -> STT round-trip; return True on pass."""
    sessions: dict[str, _SessionCollector] = {}

    def on_report(event: Event) -> None:
        report = event.assistant_handle_report_event
        if not report:
            return
        session_id = getattr(report.data, 'session_id', '')
        collector = sessions.get(session_id)
        if collector is not None:
            collector.handle(report.data)

    unsubscribe = client.subscribe_event(
        event_type=Event(assistant_handle_report_event=AssistantHandleReportEvent()),
        callback=on_report,
    )

    try:
        # --- 1. TTS, retried until the assistant subprocess is up ------------
        logger.info('Waiting for the assistant service and synthesizing speech...')
        deadline = time.monotonic() + ASSISTANT_UP_BUDGET
        tts: _SessionCollector | None = None
        while time.monotonic() < deadline:
            collector = _SessionCollector(
                session_id=f'roundtrip-tts-{uuid.uuid4().hex}',
                done=asyncio.Event(),
            )
            sessions[collector.session_id] = collector
            await _synthesize(client, collector)
            if collector.error:
                logger.error('TTS error: %s', collector.error)
                return False
            if collector.audio:
                tts = collector
                break
            logger.info('  no audio yet — assistant still starting, retrying...')

        if tts is None or not tts.audio:
            logger.error('TTS produced no audio within %ss', ASSISTANT_UP_BUDGET)
            return False

        pcm = bytes(tts.audio)
        logger.info(
            'TTS produced %d bytes (rate=%d, channels=%d)',
            len(pcm),
            tts.sample_rate,
            tts.num_channels,
        )
        _write_wav(TTS_WAV_PATH, pcm, tts.sample_rate, tts.num_channels)
        logger.info('Wrote synthesized audio to %s', TTS_WAV_PATH)

        # --- 2. STT ----------------------------------------------------------
        logger.info('Transcribing the synthesized audio...')
        stt = _SessionCollector(
            session_id=f'roundtrip-stt-{uuid.uuid4().hex}',
            done=asyncio.Event(),
        )
        sessions[stt.session_id] = stt
        await _transcribe(
            client,
            stt,
            pcm,
            tts.sample_rate or 16000,
            tts.num_channels or 1,
        )
        if stt.error:
            logger.error('STT error: %s', stt.error)
            return False

        transcription = ' '.join(stt.text_parts).strip()
        logger.info('Original:     %r', TEST_SENTENCE)
        logger.info('Transcribed:  %r', transcription)

        if not transcription:
            logger.error('STT produced no transcription')
            return False

        # --- 3. compare ------------------------------------------------------
        ratio, coverage, passed = compare(TEST_SENTENCE, transcription)
        logger.info(
            'similarity ratio = %.2f (>= %.2f), keyword coverage = %.2f (>= %.2f)',
            ratio,
            MIN_SIMILARITY_RATIO,
            coverage,
            MIN_KEYWORD_COVERAGE,
        )
    finally:
        unsubscribe()

    return passed


async def _main_async() -> int:
    client = UboRPCClient(GRPC_HOST, GRPC_PORT)
    try:
        passed = await _round_trip(client)
    finally:
        client.close()
    return 0 if passed else 1


def main() -> int:
    """Boot the app, run the round-trip, tear the app down."""
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--no-launch',
        action='store_true',
        help='assume the app is already running; do not launch or stop it',
    )
    args = parser.parse_args()

    app: subprocess.Popen | None = None
    if not args.no_launch:
        app = launch_app()

    try:
        logger.info('Waiting for the gRPC server at %s:%d...', GRPC_HOST, GRPC_PORT)
        if not wait_for_grpc(GRPC_HOST, GRPC_PORT, GRPC_UP_TIMEOUT):
            logger.error('gRPC server never came up — see %s', APP_LOG_PATH)
            return 1
        logger.info('gRPC server is up.')
        exit_code = asyncio.run(_main_async())
    finally:
        if app is not None:
            terminate_app(app)

    if exit_code == 0:
        logger.info('RESULT: PASS')
    else:
        logger.error('RESULT: FAIL')
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
