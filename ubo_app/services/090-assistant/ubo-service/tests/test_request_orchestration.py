"""Unit tests for the one-shot request orchestration logic.

These cover the pipeline-driving behavior — input-frame construction, real-time
audio pacing, and the gRPC terminal collector's dispatch / ordering / finalize
logic — using synthetic frames and a fake RPC client. They need NO provider
credentials, downloaded models, or network, so they run in CI. NOT marked
``providers`` (so ``poe test`` runs them).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, TypeAlias, cast

import betterproto
import pytest
from pipecat.frames.frames import (
    InputAudioRawFrame,
    LLMRunFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    TTSStoppedFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.deepgram.stt import DeepgramSTTService
from provider_harness import FakeUboRPCClient
from ubo_bindings.ubo.v1 import (
    AssistanceAudioFrame,
    AssistanceErrorFrame,
    AssistanceTextFrame,
    AssistantPipelineStage,
    AssistantRunPipelineEvent,
)

from ubo_assistant.grpc_collector import GRPCTerminalCollector
from ubo_assistant.pipeline_builder import LLM, STT, TTS
from ubo_assistant.request_handler import (
    _build_input_frames,
    _queue_stt_input_realtime,
    _silence_frames,
    _stt_needs_realtime_feed,
)
from ubo_assistant.segmented_googlestt import SegmentedGoogleSTTService
from ubo_assistant.vosk import VoskSTTService

if TYPE_CHECKING:
    from collections.abc import Callable

    from pipecat.pipeline.task import PipelineTask
    from ubo_bindings.client import UboRPCClient
    from ubo_bindings.ubo.v1 import Action

_DOWN = FrameDirection.DOWNSTREAM

_ReportFrame: TypeAlias = (
    AssistanceAudioFrame | AssistanceTextFrame | AssistanceErrorFrame
)


def _report_frame(action: Action) -> _ReportFrame | None:
    """Return the report's inner frame (audio/text/error), narrowed by isinstance."""
    _, frame = betterproto.which_one_of(
        action.assistant_report_action.data,
        'acceptable_assistance_frame',
    )
    if isinstance(
        frame,
        (AssistanceAudioFrame, AssistanceTextFrame, AssistanceErrorFrame),
    ):
        return frame
    return None


def _report_frames(client: FakeUboRPCClient) -> list[_ReportFrame]:
    """All report frames captured by the fake client, in dispatch order."""
    return [frame for action in client.frames if (frame := _report_frame(action))]


def _collector(client: object, stage: AssistantPipelineStage) -> GRPCTerminalCollector:
    """Build a collector for a duck-typed fake client."""
    return GRPCTerminalCollector(
        client=cast('UboRPCClient', client),
        session_id='s',
        terminal_stage=stage,
    )


# --------------------------------------------------------------------------- #
# _build_input_frames                                                         #
# --------------------------------------------------------------------------- #


def test_build_input_frames_stt_brackets_audio_with_vad() -> None:
    """STT input is bracketed by VAD speaking frames around the audio."""
    event = AssistantRunPipelineEvent(
        audio=b'\x01\x02' * 800,
        sample_rate=16000,
        num_channels=1,
    )
    frames = _build_input_frames([STT], event)

    assert isinstance(frames[0], VADUserStartedSpeakingFrame)
    assert isinstance(frames[-1], VADUserStoppedSpeakingFrame)
    assert any(isinstance(frame, InputAudioRawFrame) for frame in frames)


def test_build_input_frames_llm_is_run_frame() -> None:
    """LLM-first input triggers a completion with a single LLMRunFrame."""
    frames = _build_input_frames([LLM], AssistantRunPipelineEvent(text='hi'))
    assert len(frames) == 1
    assert isinstance(frames[0], LLMRunFrame)


def test_build_input_frames_tts_is_speak_frame() -> None:
    """TTS-first input synthesizes via a TTSSpeakFrame carrying the text."""
    frames = _build_input_frames([TTS], AssistantRunPipelineEvent(text='hello there'))
    assert len(frames) == 1
    assert isinstance(frames[0], TTSSpeakFrame)
    assert frames[0].text == 'hello there'


# --------------------------------------------------------------------------- #
# _silence_frames / _stt_needs_realtime_feed                                  #
# --------------------------------------------------------------------------- #


def test_silence_frames_count_and_content() -> None:
    """1s of 16kHz mono silence is 50 chunk-sized all-zero frames."""
    frames = _silence_frames(1.0, 16000, 1)
    # 16000 samples * 2 bytes * 1 ch = 32000 bytes / 640 = 50 frames.
    assert len(frames) == 50
    assert all(isinstance(frame, InputAudioRawFrame) for frame in frames)
    assert all(
        cast('InputAudioRawFrame', frame).audio == b'\x00' * 640 for frame in frames
    )


def test_realtime_feed_for_cloud_streaming_not_segmented_or_vosk() -> None:
    """Cloud streaming STT needs the paced lead-in; segmented/Vosk burst."""
    # ``__new__`` builds an instance without the heavy provider __init__ (no API
    # key / model load) — the detector only isinstance-checks. Real classes, not
    # stubs, so this pins the actual taxonomy: Deepgram streams, Google-segmented
    # and Vosk buffer.
    assert _stt_needs_realtime_feed(DeepgramSTTService.__new__(DeepgramSTTService))
    assert not _stt_needs_realtime_feed(
        SegmentedGoogleSTTService.__new__(SegmentedGoogleSTTService),
    )
    assert not _stt_needs_realtime_feed(VoskSTTService.__new__(VoskSTTService))


# --------------------------------------------------------------------------- #
# _queue_stt_input_realtime pacing                                            #
# --------------------------------------------------------------------------- #


class _FakeTask:
    """Records the frames queued onto it, in order."""

    def __init__(self) -> None:
        """Start with no queued frames."""
        self.queued: list[object] = []

    async def queue_frame(self, frame: object) -> None:
        """Record a queued frame."""
        self.queued.append(frame)


async def test_pacing_mono_sleeps_real_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mono audio is paced at its real-time duration."""
    sleeps: list[float] = []

    async def _fake_sleep(duration: float) -> None:
        sleeps.append(duration)

    monkeypatch.setattr(asyncio, 'sleep', _fake_sleep)
    task = _FakeTask()
    # 3200 bytes mono int16 @ 16 kHz = 1600 samples = 0.1 s.
    frame = InputAudioRawFrame(audio=b'\x00' * 3200, sample_rate=16000, num_channels=1)

    await _queue_stt_input_realtime(cast('PipelineTask', task), [frame], 16000)

    assert task.queued == [frame]
    assert sleeps == pytest.approx([0.1])


async def test_pacing_accounts_for_channel_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stereo audio paces by frame count (channels), not byte count."""
    sleeps: list[float] = []

    async def _fake_sleep(duration: float) -> None:
        sleeps.append(duration)

    monkeypatch.setattr(asyncio, 'sleep', _fake_sleep)
    task = _FakeTask()
    # Same 3200 bytes but stereo = 800 frames @ 16 kHz = 0.05 s (not 0.1 s).
    frame = InputAudioRawFrame(audio=b'\x00' * 3200, sample_rate=16000, num_channels=2)

    await _queue_stt_input_realtime(cast('PipelineTask', task), [frame], 16000)

    assert sleeps == pytest.approx([0.05])


# --------------------------------------------------------------------------- #
# GRPCTerminalCollector                                                       #
# --------------------------------------------------------------------------- #


async def test_collector_tts_end_marker_routed_through_report_path() -> None:
    """The end marker is an AssistanceAudioFrame report, not a direct AudioPlay."""
    client = FakeUboRPCClient()
    collector = _collector(client, AssistantPipelineStage.TTS)

    await collector.process_frame(
        TTSAudioRawFrame(audio=b'\x10\x20' * 50, sample_rate=48000, num_channels=1),
        _DOWN,
    )
    await collector.process_frame(TTSStoppedFrame(), _DOWN)

    # Every dispatched action is a report — the collector never dispatches a raw
    # AudioPlayAudioSequenceAction itself (the racing direct-dispatch the fix
    # removed).
    assert all(
        betterproto.which_one_of(action, 'action')[0] == 'assistant_report_action'
        for action in client.frames
    )
    audio_frames = [
        frame
        for frame in _report_frames(client)
        if isinstance(frame, AssistanceAudioFrame)
    ]
    assert audio_frames[0].audio is not None  # the real chunk
    assert audio_frames[-1].audio is None  # the end marker
    assert audio_frames[-1].is_last_frame
    assert collector.last_output.is_set()


async def test_collector_resamples_odd_length_chunk_without_error() -> None:
    """An odd-length non-48k TTS chunk resamples cleanly (the Rime crash).

    soxr reads the bytes as int16, so a chunk whose length is an odd number of
    bytes — a sample split across two websocket frames, which Rime intermittently
    emits — would raise "buffer size must be a multiple of element size". The
    collector must carry the partial sample to the next chunk instead.
    """
    client = FakeUboRPCClient()
    collector = _collector(client, AssistantPipelineStage.TTS)

    # 24 kHz forces a resample to 48 kHz; 1001 bytes = 500 whole samples + 1 byte.
    await collector.process_frame(
        TTSAudioRawFrame(
            audio=b'\x11\x22' * 500 + b'\x33',
            sample_rate=24000,
            num_channels=1,
        ),
        _DOWN,
    )
    # The carried byte completes here; the full stream still comes through.
    await collector.process_frame(
        TTSAudioRawFrame(
            audio=b'\x44' + b'\x55\x66' * 500,
            sample_rate=24000,
            num_channels=1,
        ),
        _DOWN,
    )
    await collector.process_frame(TTSStoppedFrame(), _DOWN)

    frames = _report_frames(client)
    assert not any(isinstance(frame, AssistanceErrorFrame) for frame in frames)
    assert any(
        isinstance(frame, AssistanceAudioFrame) and frame.audio for frame in frames
    )
    assert collector.audio_rate == 48000


class _OrderingClient:
    """Fake client whose dispatch completes asynchronously, recording order.

    Logs ``('dispatch', kind)`` when an action is dispatched and
    ``('delivered', kind)`` when its simulated gRPC call completes, so a test can
    assert the end marker isn't dispatched until the audio chunk is delivered.
    """

    def __init__(self) -> None:
        """Start with an empty event log."""
        self.log: list[tuple[str, str]] = []

    @property
    def event_loop(self) -> asyncio.AbstractEventLoop:
        """The running loop (the collector timestamps against it)."""
        return asyncio.get_running_loop()

    def dispatch(self, *, action: Action) -> asyncio.Task[None]:
        """Record the dispatch and deliver it after a short async delay."""
        frame = _report_frame(action)
        if isinstance(frame, AssistanceAudioFrame):
            kind = 'marker' if frame.audio is None else 'audio'
        elif isinstance(frame, AssistanceTextFrame):
            kind = 'text'
        elif isinstance(frame, AssistanceErrorFrame):
            kind = 'error'
        else:
            kind = 'other'
        self.log.append(('dispatch', kind))

        async def _deliver() -> None:
            await asyncio.sleep(0.02)
            self.log.append(('delivered', kind))

        return asyncio.ensure_future(_deliver())

    async def query_secret(self, *_args: object, **_kwargs: object) -> None:
        """Unused secret lookup."""

    def subscribe_event(self, *_args: object, **_kwargs: object) -> Callable[[], None]:
        """Unused event subscription."""
        return lambda: None


async def test_collector_end_marker_dispatched_after_audio_delivery() -> None:
    """The end marker waits for in-flight chunk dispatches before it is sent.

    Reproduces the race the fix guards against: with a client whose dispatch
    completes asynchronously, the marker must not be dispatched until the audio
    chunk has been delivered to the server.
    """
    client = _OrderingClient()
    collector = _collector(client, AssistantPipelineStage.TTS)

    await collector.process_frame(
        TTSAudioRawFrame(audio=b'\x10\x20' * 50, sample_rate=48000, num_channels=1),
        _DOWN,
    )
    await collector.process_frame(TTSStoppedFrame(), _DOWN)
    await asyncio.sleep(0.05)  # let the marker/text deliveries finish

    assert ('delivered', 'audio') in client.log
    assert ('dispatch', 'marker') in client.log
    assert client.log.index(('delivered', 'audio')) < client.log.index(
        ('dispatch', 'marker'),
    )


async def test_collector_error_dispatched_after_audio_delivery() -> None:
    """A terminal error waits for in-flight chunk dispatches before it is sent.

    If a provider emits some audio and then raises, the ``is_last_frame`` error
    must not overtake the still in-flight audio report (same ordering barrier as
    the success end-marker).
    """
    client = _OrderingClient()
    collector = _collector(client, AssistantPipelineStage.TTS)

    await collector.process_frame(
        TTSAudioRawFrame(audio=b'\x10\x20' * 50, sample_rate=48000, num_channels=1),
        _DOWN,
    )
    await collector.dispatch_error('boom')
    await asyncio.sleep(0.05)  # let the error delivery finish

    assert ('delivered', 'audio') in client.log
    assert ('dispatch', 'error') in client.log
    assert client.log.index(('delivered', 'audio')) < client.log.index(
        ('dispatch', 'error'),
    )


async def test_collector_stt_finalized_signal() -> None:
    """A finalized transcript sets ``stt_finalized``; every transcript is sent."""
    client = FakeUboRPCClient()
    collector = _collector(client, AssistantPipelineStage.STT)

    await collector.process_frame(
        TranscriptionFrame(text='the quick', user_id='', timestamp=''),
        _DOWN,
    )
    assert not collector.stt_finalized.is_set()

    finalized = TranscriptionFrame(text='brown fox', user_id='', timestamp='')
    finalized.finalized = True
    await collector.process_frame(finalized, _DOWN)

    assert collector.stt_finalized.is_set()
    assert collector.first_output.is_set()
    texts = [
        frame.text
        for frame in _report_frames(client)
        if isinstance(frame, AssistanceTextFrame)
    ]
    assert texts == ['the quick', 'brown fox']


async def test_collector_dispatch_error_is_terminal_and_idempotent() -> None:
    """dispatch_error sends one error frame and sets the terminal events."""
    client = FakeUboRPCClient()
    collector = _collector(client, AssistantPipelineStage.TTS)

    await collector.dispatch_error('boom')
    await collector.dispatch_error('again')  # idempotent — ignored

    assert len(client.frames) == 1
    frame = _report_frame(client.frames[0])
    assert isinstance(frame, AssistanceErrorFrame)
    assert frame.error == 'boom'
    assert collector.first_output.is_set()
    assert collector.last_output.is_set()
