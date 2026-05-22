# ruff: noqa
"""Disposable end-to-end test for the assistant's gRPC pipeline.

Boots the ubo app, waits for the assistant service to come up, then runs one
scenario per pipeline shape against the gRPC API:

  - tts-stt-roundtrip  — synthesize a sentence, transcribe it back, fuzzy-match.
  - llm-<provider>     — LLM completion, provider selected per-request over gRPC
    (exercises programmatic provider selection / service switching).
  - llm-tts-<provider> — text -> LLM -> TTS; the LLM echoes a fixed sentence and
    the spoken output is fed back through STT and fuzzy-matched.
  - stt-llm-<provider> — STT -> LLM -> text; the input audio is TTS-generated.

This is a standalone manual test — NOT wired into the pytest suite or CI (see
tools/test_tts_stt_roundtrip.md for the deferred CI/CD integration plan). Run it
from the repo root on a machine where the providers are set up:

    uv run python tools/test_tts_stt_roundtrip.py

A scenario whose STT/TTS/LLM provider is not set up is SKIPPED with an explicit
message — not failed — so the test degrades gracefully. Point TTS_PROVIDER /
STT_PROVIDER / LLM_PROVIDERS at whatever is available on this machine.

Exit code 0 = nothing failed (skips are fine), 1 = at least one scenario failed.
The app's output is teed to ./ubo-app-roundtrip.log and the synthesized audio
to /tmp/ubo-roundtrip-tts.wav for inspection.
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
    AssistantCompleteAction,
    AssistantHandleReportEvent,
    AssistantLlmName,
    AssistantPipelineStage,
    AssistantRunPipelineAction,
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

# Local providers for the TTS->STT round-trip — no API keys needed.
TTS_PROVIDER = AssistantTtsName.PIPER
STT_PROVIDER = AssistantSttName.VOSK

# LLM engines to exercise. Each is selected per-request over the gRPC API; an
# engine that is not configured comes back as an error frame and fails its
# scenario. Edit this list to match what is set up on the machine.
LLM_PROVIDERS = ['openai', 'anthropic']
# A question whose words — and whose answer — the small Vosk model transcribes
# reliably. Proper nouns (e.g. "Paris"/"France") do not survive a TTS->STT round
# trip with the small model, so the LLM-in-a-chain scenarios use plain words.
LLM_QUESTION = 'What color is the sky?'
LLM_SYSTEM_PROMPT = 'Answer the question in one short, plain English sentence.'
LLM_EXPECTED_KEYWORD = 'blue'
# The llm-tts chain feeds the LLM's *spoken* output through STT, so it must be a
# long, STT-robust phrase — a short free-form answer ("The sky is blue.") gets
# mangled by the small Vosk model. The LLM is asked to echo TEST_SENTENCE
# verbatim, and the transcription is fuzzy-matched against it.
LLM_ECHO_PROMPT = (
    'Repeat the user message back to me exactly, word for word, with no '
    'additions, preface, or commentary.'
)

GRPC_UP_TIMEOUT = 120.0  # seconds to wait for the core gRPC server
ASSISTANT_UP_BUDGET = 240.0  # total seconds to keep retrying for the assistant
SYNTHESIS_TIMEOUT = 45.0  # per-attempt seconds to wait for TTS output
TRANSCRIPTION_TIMEOUT = 60.0  # seconds to wait for STT output
LLM_TIMEOUT = 90.0  # seconds to wait for an LLM completion
CHAIN_TIMEOUT = 90.0  # seconds to wait for a multi-stage chain (STT/LLM/TTS)

APP_LOG_PATH = REPO_ROOT / 'ubo-app-roundtrip.log'
TTS_WAV_PATH = Path('/tmp/ubo-roundtrip-tts.wav')

# Pass thresholds for STT — it is lossy, so lean on keyword coverage.
MIN_SIMILARITY_RATIO = 0.6
MIN_KEYWORD_COVERAGE = 0.5
_KEYWORD_MIN_LEN = 4

# betterproto enum member (lower-cased) -> enum value, for selecting providers.
_LLM_PROVIDER_BY_NAME = {
    member.name.lower(): member
    for member in AssistantLlmName.__members__.values()
    if member.value != 0
}


@dataclass
class ScenarioResult:
    """Outcome of one test scenario — status is 'PASS', 'FAIL' or 'SKIP'."""

    name: str
    status: str
    detail: str


# Error-frame messages from the request handler that mean a provider is simply
# not set up on this machine (vs. a genuine failure). These turn a scenario into
# SKIP rather than FAIL — see _resolve_stage_services in request_handler.py.
_UNAVAILABLE_MARKERS = ('not available', 'not configured', 'unknown ')


def _is_provider_unavailable(error: str) -> bool:
    """Whether an error-frame message means a provider is not set up."""
    low = error.lower()
    return any(marker in low for marker in _UNAVAILABLE_MARKERS)


def _from_error(name: str, error: str) -> ScenarioResult:
    """Classify an error-frame message into a SKIP (not set up) or FAIL result."""
    if _is_provider_unavailable(error):
        return ScenarioResult(name, 'SKIP', f'provider not set up: {error}')
    return ScenarioResult(name, 'FAIL', error)


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
    return subprocess.Popen(
        LAUNCH_COMMAND,
        cwd=REPO_ROOT,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def kill_stale_ubo_processes() -> None:
    """Best-effort: kill leftover ubo processes from a previous (crashed) run.

    A run whose teardown did not complete (e.g. the script was killed) leaves a
    core holding the gRPC port; the next run would then silently talk to that
    zombie. This clears the slate.
    """
    for pattern in ('ubo-assistant', 'ubo_app.main', 'uv run ubo', 'ubo_gui_client'):
        with contextlib.suppress(Exception):
            subprocess.run(['pkill', '-9', '-f', pattern], check=False)  # noqa: S603, S607
    # Free the gRPC port if a zombie still holds it.
    with contextlib.suppress(Exception):
        result = subprocess.run(  # noqa: S603, S607
            ['lsof', '-ti', f'tcp:{GRPC_PORT}'],
            capture_output=True,
            text=True,
            check=False,
        )
        for pid in result.stdout.split():
            with contextlib.suppress(Exception):
                os.kill(int(pid), signal.SIGKILL)


def terminate_app(process: subprocess.Popen) -> None:
    """Stop the app and best-effort clean up its subprocesses."""
    logger.info('Stopping the app (pid=%d)', process.pid)
    with contextlib.suppress(ProcessLookupError):
        process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    # The assistant/GUI subprocesses start their own sessions — sweep them too.
    kill_stale_ubo_processes()


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


def _new_session(sessions: dict[str, _SessionCollector], prefix: str) -> _SessionCollector:
    collector = _SessionCollector(
        session_id=f'{prefix}-{uuid.uuid4().hex}',
        done=asyncio.Event(),
    )
    sessions[collector.session_id] = collector
    return collector


# --- request helpers ---------------------------------------------------------
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


async def _complete(
    client: UboRPCClient,
    collector: _SessionCollector,
    provider: AssistantLlmName,
) -> None:
    """Dispatch an LLM completion request and wait for the response."""
    client.dispatch(
        action=Action(
            assistant_complete_action=AssistantCompleteAction(
                text=LLM_QUESTION,
                session_id=collector.session_id,
                llm_provider=provider,
                system_prompt=LLM_SYSTEM_PROMPT,
                enable_tools=False,
            ),
        ),
    )
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(collector.done.wait(), timeout=LLM_TIMEOUT)


async def _run_pipeline(
    client: UboRPCClient,
    collector: _SessionCollector,
    *,
    stages: list[AssistantPipelineStage],
    timeout: float,
    text: str = '',
    audio: bytes = b'',
    sample_rate: int = 16000,
    num_channels: int = 1,
    stt_provider: AssistantSttName | None = None,
    llm_provider: AssistantLlmName | None = None,
    tts_provider: AssistantTtsName | None = None,
    system_prompt: str = '',
) -> None:
    """Dispatch a parametrized AssistantRunPipelineAction and wait for completion."""
    kwargs: dict = {
        'session_id': collector.session_id,
        'stages': stages,
        'text': text,
        'audio': audio,
        'sample_rate': sample_rate,
        'num_channels': num_channels,
    }
    if stt_provider is not None:
        kwargs['stt_provider'] = stt_provider
    if llm_provider is not None:
        kwargs['llm_provider'] = llm_provider
    if tts_provider is not None:
        kwargs['tts_provider'] = tts_provider
    if system_prompt:
        kwargs['system_prompt'] = system_prompt
    client.dispatch(
        action=Action(
            assistant_run_pipeline_action=AssistantRunPipelineAction(**kwargs),
        ),
    )
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(collector.done.wait(), timeout=timeout)


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


# --- scenarios ---------------------------------------------------------------
async def _scenario_tts_stt(
    client: UboRPCClient,
    sessions: dict[str, _SessionCollector],
) -> ScenarioResult:
    """TTS -> STT round-trip, retried until the assistant subprocess is up."""
    name = 'tts-stt-roundtrip'
    logger.info('[%s] waiting for the assistant service and synthesizing...', name)
    deadline = time.monotonic() + ASSISTANT_UP_BUDGET
    tts: _SessionCollector | None = None
    while time.monotonic() < deadline:
        collector = _new_session(sessions, 'roundtrip-tts')
        await _synthesize(client, collector)
        # An error frame means the assistant IS up — it just can't serve this
        # provider (skip) or hit a real failure (fail).
        if collector.error:
            return _from_error(name, collector.error)
        if collector.audio:
            tts = collector
            break
        logger.info('  no audio yet — assistant still starting, retrying...')

    if tts is None or not tts.audio:
        # No response at all within the budget — the assistant never came up.
        return ScenarioResult(
            name,
            'FAIL',
            f'assistant produced no response within {ASSISTANT_UP_BUDGET}s',
        )

    pcm = bytes(tts.audio)
    logger.info(
        '[%s] TTS produced %d bytes (rate=%d, channels=%d)',
        name,
        len(pcm),
        tts.sample_rate,
        tts.num_channels,
    )
    _write_wav(TTS_WAV_PATH, pcm, tts.sample_rate, tts.num_channels)

    stt = _new_session(sessions, 'roundtrip-stt')
    await _transcribe(client, stt, pcm, tts.sample_rate or 16000, tts.num_channels or 1)
    if stt.error:
        return _from_error(name, stt.error)

    transcription = ' '.join(stt.text_parts).strip()
    logger.info('[%s] original:    %r', name, TEST_SENTENCE)
    logger.info('[%s] transcribed: %r', name, transcription)
    if not transcription:
        return ScenarioResult(name, 'FAIL', 'STT produced no transcription')

    ratio, coverage, passed = compare(TEST_SENTENCE, transcription)
    return ScenarioResult(
        name,
        'PASS' if passed else 'FAIL',
        f'ratio={ratio:.2f} coverage={coverage:.2f} -> {transcription!r}',
    )


async def _scenario_llm(
    client: UboRPCClient,
    sessions: dict[str, _SessionCollector],
    provider_name: str,
) -> ScenarioResult:
    """LLM completion for one provider, selected per-request over gRPC."""
    name = f'llm-{provider_name}'
    provider = _LLM_PROVIDER_BY_NAME.get(provider_name)
    if provider is None:
        return ScenarioResult(name, 'FAIL', f'unknown LLM provider id: {provider_name}')

    logger.info('[%s] asking %r ...', name, LLM_QUESTION)
    collector = _new_session(sessions, f'roundtrip-llm-{provider_name}')
    await _complete(client, collector, provider)
    if collector.error:
        return _from_error(name, collector.error)

    response = ' '.join(collector.text_parts).strip()
    logger.info('[%s] response: %r', name, response)
    if not response:
        return ScenarioResult(name, 'FAIL', 'LLM produced no response')

    status = 'PASS' if LLM_EXPECTED_KEYWORD in response.lower() else 'FAIL'
    detail = f'{response!r} (expected keyword {LLM_EXPECTED_KEYWORD!r})'
    return ScenarioResult(name, status, detail)


async def _scenario_llm_tts(
    client: UboRPCClient,
    sessions: dict[str, _SessionCollector],
    provider_name: str,
) -> ScenarioResult:
    """text -> LLM -> TTS chain; the spoken output is fed to STT to verify it.

    The LLM is asked to echo a fixed, STT-robust sentence so the assertion does
    not hinge on Vosk transcribing a short, free-form answer.
    """
    name = f'llm-tts-{provider_name}'
    provider = _LLM_PROVIDER_BY_NAME.get(provider_name)
    if provider is None:
        return ScenarioResult(name, 'FAIL', f'unknown LLM provider id: {provider_name}')

    # text -> LLM -> TTS  =>  audio of the assistant speaking the echoed sentence
    logger.info('[%s] running text -> LLM -> TTS ...', name)
    spoken = _new_session(sessions, f'roundtrip-llmtts-{provider_name}')
    await _run_pipeline(
        client,
        spoken,
        stages=[AssistantPipelineStage.LLM, AssistantPipelineStage.TTS],
        text=TEST_SENTENCE,
        llm_provider=provider,
        tts_provider=TTS_PROVIDER,
        system_prompt=LLM_ECHO_PROMPT,
        timeout=CHAIN_TIMEOUT,
    )
    if spoken.error:
        return _from_error(name, spoken.error)
    if not spoken.audio:
        return ScenarioResult(name, 'FAIL', 'LLM->TTS produced no audio')

    # audio -> STT  =>  transcription of the spoken answer, for assertion
    heard = _new_session(sessions, f'roundtrip-llmtts-stt-{provider_name}')
    await _run_pipeline(
        client,
        heard,
        stages=[AssistantPipelineStage.STT],
        audio=bytes(spoken.audio),
        sample_rate=spoken.sample_rate or 16000,
        num_channels=spoken.num_channels or 1,
        stt_provider=STT_PROVIDER,
        timeout=TRANSCRIPTION_TIMEOUT,
    )
    if heard.error:
        return _from_error(name, heard.error)

    transcription = ' '.join(heard.text_parts).strip()
    logger.info('[%s] echoed sentence transcribed back as: %r', name, transcription)
    ratio, coverage, passed = compare(TEST_SENTENCE, transcription)
    return ScenarioResult(
        name,
        'PASS' if passed else 'FAIL',
        f'ratio={ratio:.2f} coverage={coverage:.2f} -> {transcription!r}',
    )


async def _scenario_stt_llm(
    client: UboRPCClient,
    sessions: dict[str, _SessionCollector],
    provider_name: str,
) -> ScenarioResult:
    """STT -> LLM -> text chain; the input audio is TTS-generated from a question."""
    name = f'stt-llm-{provider_name}'
    provider = _LLM_PROVIDER_BY_NAME.get(provider_name)
    if provider is None:
        return ScenarioResult(name, 'FAIL', f'unknown LLM provider id: {provider_name}')

    # TTS-generate the spoken question — input audio for the STT -> LLM chain
    logger.info('[%s] synthesizing the spoken question ...', name)
    question = _new_session(sessions, f'roundtrip-sttllm-tts-{provider_name}')
    await _run_pipeline(
        client,
        question,
        stages=[AssistantPipelineStage.TTS],
        text=LLM_QUESTION,
        tts_provider=TTS_PROVIDER,
        timeout=SYNTHESIS_TIMEOUT,
    )
    if question.error:
        return _from_error(name, question.error)
    if not question.audio:
        return ScenarioResult(name, 'FAIL', 'question TTS produced no audio')

    # audio -> STT -> LLM  =>  the assistant's text answer
    logger.info('[%s] running STT -> LLM ...', name)
    answer = _new_session(sessions, f'roundtrip-sttllm-{provider_name}')
    await _run_pipeline(
        client,
        answer,
        stages=[AssistantPipelineStage.STT, AssistantPipelineStage.LLM],
        audio=bytes(question.audio),
        sample_rate=question.sample_rate or 16000,
        num_channels=question.num_channels or 1,
        stt_provider=STT_PROVIDER,
        llm_provider=provider,
        system_prompt=LLM_SYSTEM_PROMPT,
        timeout=CHAIN_TIMEOUT,
    )
    if answer.error:
        return _from_error(name, answer.error)

    response = ' '.join(answer.text_parts).strip()
    logger.info('[%s] answer: %r', name, response)
    if not response:
        return ScenarioResult(name, 'FAIL', 'STT->LLM produced no response')

    status = 'PASS' if LLM_EXPECTED_KEYWORD in response.lower() else 'FAIL'
    return ScenarioResult(
        name,
        status,
        f'{response!r} (expected keyword {LLM_EXPECTED_KEYWORD!r})',
    )


# --- orchestration -----------------------------------------------------------
async def _run_scenarios(client: UboRPCClient) -> list[ScenarioResult]:
    """Subscribe to report events and run every scenario."""
    sessions: dict[str, _SessionCollector] = {}

    def on_report(event: Event) -> None:
        report = event.assistant_handle_report_event
        if not report:
            return
        # `session_id` lives on the inner Assistance*Frame, not on the
        # AcceptableAssistanceFrame oneof wrapper.
        field_name = _active_field(report.data)
        if field_name is None:
            return
        inner = getattr(report.data, field_name)
        collector = sessions.get(getattr(inner, 'session_id', ''))
        if collector is not None:
            collector.handle(report.data)

    unsubscribe = client.subscribe_event(
        event_type=Event(assistant_handle_report_event=AssistantHandleReportEvent()),
        callback=on_report,
    )

    results: list[ScenarioResult] = []
    try:
        # The first scenario doubles as the wait-for-assistant-startup loop.
        results.append(await _scenario_tts_stt(client, sessions))
        for provider_name in LLM_PROVIDERS:
            results.append(await _scenario_llm(client, sessions, provider_name))
            results.append(await _scenario_llm_tts(client, sessions, provider_name))
            results.append(await _scenario_stt_llm(client, sessions, provider_name))
    finally:
        unsubscribe()

    return results


async def _main_async() -> int:
    client = UboRPCClient(GRPC_HOST, GRPC_PORT)
    try:
        results = await _run_scenarios(client)
    finally:
        client.close()

    failed = [r for r in results if r.status == 'FAIL']
    skipped = [r for r in results if r.status == 'SKIP']
    passed = [r for r in results if r.status == 'PASS']
    logger.info('=== SCENARIO RESULTS ===')
    for result in results:
        logger.info('  [%s] %-22s : %s', result.status, result.name, result.detail)
    logger.info(
        'summary: %d passed, %d skipped, %d failed',
        len(passed),
        len(skipped),
        len(failed),
    )
    if skipped:
        logger.info(
            'skipped scenarios need an STT/TTS/LLM provider that is not set up '
            'here — expected, not a failure.',
        )
    return 0 if not failed else 1


def main() -> int:
    """Boot the app, run the scenarios, tear the app down."""
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
        # A previous crashed run can leave a core holding the gRPC port; clear
        # it so this run does not silently talk to a zombie.
        kill_stale_ubo_processes()
        time.sleep(1.0)
        port_in_use = False
        with contextlib.suppress(OSError):
            with socket.create_connection((GRPC_HOST, GRPC_PORT), timeout=1):
                port_in_use = True
        if port_in_use:
            logger.error(
                'port %d still in use after cleanup — aborting (kill it manually)',
                GRPC_PORT,
            )
            return 1
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

    logger.info('RESULT: %s', 'PASS' if exit_code == 0 else 'FAIL')
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
