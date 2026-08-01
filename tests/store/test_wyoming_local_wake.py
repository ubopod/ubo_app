"""The satellite streams the microphone only between a local wake and its end.

Home Assistant is asked to run its pipeline from the ASR stage, so it never needs
a wake-word engine of its own — that is what lets it work on a Home Assistant
install that cannot add the openWakeWord add-on (Docker rather than HA OS).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from wyoming.asr import Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncTcpClient
from wyoming.pipeline import PipelineStage, RunPipeline
from wyoming.satellite import RunSatellite
from wyoming.vad import VoiceStopped
from wyoming.wake import Detection

from ubo_app.store.services.wyoming import WyomingConnectionPolicy

SERVICE_DIR = (
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '090-wyoming'
)
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from security import PeerAccess  # noqa: E402  # type: ignore[reportMissingImports]

_SAMPLE = b'\x01\x02' * 160


async def _read_until(client: AsyncTcpClient, predicate: object) -> object:
    """Return the first event matching *predicate*, or fail on timeout."""
    while True:
        event = await asyncio.wait_for(client.read_event(), timeout=2)
        assert event is not None, 'satellite closed the connection'
        if predicate(event):  # type: ignore[operator]
            return event


async def _assert_no_audio_chunk(client: AsyncTcpClient) -> None:
    """Fail if the satellite puts microphone audio on the wire."""
    with pytest.raises(TimeoutError):
        await _read_until(client, lambda event: AudioChunk.is_type(event.type))


def _ring_actions(dispatched: list[object], name: str) -> list[object]:
    """Select dispatched ring actions by class name.

    Matched by name rather than ``isinstance``: integration tests earlier in the
    suite wipe ``sys.modules``, so the class this file imports is not always the
    one the service holds.
    """
    return [action for action in dispatched if type(action).__name__ == name]


@pytest.fixture
def _immediate_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the service-context task runner, absent under bare pytest."""
    import satellite  # type: ignore[reportMissingImports]

    monkeypatch.setattr(
        satellite,
        'create_task',
        lambda coroutine, *_args, **_kwargs: asyncio.get_running_loop().create_task(
            coroutine,
        ),
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures('_immediate_tasks')
async def test_microphone_stays_local_until_a_wake_word_fires() -> None:
    """An idle satellite must not put the microphone on the network.

    The whole point of detecting the wake word on-device: between commands the
    audio never leaves the pod.
    """
    from satellite import SatelliteServer  # type: ignore[reportMissingImports]

    server = SatelliteServer(
        host='127.0.0.1',
        port=0,
        access=PeerAccess(policy=WyomingConnectionPolicy.LOCAL_ONLY),
    )
    await server.start()
    port = server._server._server.sockets[0].getsockname()[1]  # noqa: SLF001

    try:
        async with AsyncTcpClient('127.0.0.1', port) as client:
            await client.write_event(RunSatellite().event())
            await asyncio.sleep(0.1)

            for _ in range(20):
                await server.enqueue_microphone(_SAMPLE)

            await _assert_no_audio_chunk(client)
    finally:
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.usefixtures('_immediate_tasks')
async def test_wake_requests_a_pipeline_that_skips_home_assistant_wake_word() -> None:
    """The run must start at ASR, so no wake-word engine is required upstream."""
    from satellite import SatelliteServer  # type: ignore[reportMissingImports]

    server = SatelliteServer(
        host='127.0.0.1',
        port=0,
        access=PeerAccess(policy=WyomingConnectionPolicy.LOCAL_ONLY),
    )
    await server.start()
    port = server._server._server.sockets[0].getsockname()[1]  # noqa: SLF001

    try:
        async with AsyncTcpClient('127.0.0.1', port) as client:
            await client.write_event(RunSatellite().event())
            await asyncio.sleep(0.1)
            await server.wake('hey home assistant', 'vosk')

            detection = await _read_until(
                client,
                lambda event: Detection.is_type(event.type),
            )
            assert Detection.from_event(detection).name == 'hey home assistant'  # type: ignore[arg-type]

            run = await _read_until(
                client,
                lambda event: RunPipeline.is_type(event.type),
            )
            pipeline = RunPipeline.from_event(run)  # type: ignore[arg-type]
            assert pipeline.start_stage == PipelineStage.ASR
            assert pipeline.end_stage == PipelineStage.TTS
            # Restarting on end would put the satellite back to always-streaming;
            # the next run comes from the next local wake instead.
            assert not pipeline.restart_on_end

            await _read_until(client, lambda event: AudioStart.is_type(event.type))
            for _ in range(5):
                await server.enqueue_microphone(_SAMPLE)
            chunk = await _read_until(
                client,
                lambda event: AudioChunk.is_type(event.type),
            )
            assert AudioChunk.from_event(chunk).audio == _SAMPLE  # type: ignore[arg-type]
    finally:
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.usefixtures('_immediate_tasks')
@pytest.mark.parametrize(
    'terminator',
    [Transcript(text='turn on the lights'), VoiceStopped()],
    ids=['transcript', 'voice-stopped'],
)
async def test_end_of_command_releases_the_microphone(terminator: object) -> None:
    """Both of Home Assistant's end-of-command signals must stop the stream.

    ``voice-stopped`` only arrives when Home Assistant runs its own voice-activity
    detection, which depends on the speech-to-text provider; ``transcript`` is the
    one a provider that endpoints internally still sends.
    """
    from satellite import SatelliteServer  # type: ignore[reportMissingImports]

    server = SatelliteServer(
        host='127.0.0.1',
        port=0,
        access=PeerAccess(policy=WyomingConnectionPolicy.LOCAL_ONLY),
    )
    await server.start()
    port = server._server._server.sockets[0].getsockname()[1]  # noqa: SLF001

    try:
        async with AsyncTcpClient('127.0.0.1', port) as client:
            await client.write_event(RunSatellite().event())
            await asyncio.sleep(0.1)
            await server.wake('hey home assistant', 'vosk')
            await _read_until(client, lambda event: AudioStart.is_type(event.type))

            await client.write_event(terminator.event())  # type: ignore[attr-defined]
            await _read_until(client, lambda event: AudioStop.is_type(event.type))

            for _ in range(20):
                await server.enqueue_microphone(_SAMPLE)
            await _assert_no_audio_chunk(client)
    finally:
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.usefixtures('_immediate_tasks')
@pytest.mark.parametrize(
    'ending',
    ['transcript', 'disconnect'],
)
async def test_the_ring_shows_when_home_assistant_is_listening(
    monkeypatch: pytest.MonkeyPatch,
    ending: str,
) -> None:
    """The ring lights on hand-off and darkens however the utterance ends.

    The teardown case matters most: a dropped socket mid-command must not leave
    the ring lit with nothing listening.
    """
    import satellite  # type: ignore[reportMissingImports]
    from satellite import SatelliteServer  # type: ignore[reportMissingImports]

    server = SatelliteServer(
        host='127.0.0.1',
        port=0,
        access=PeerAccess(policy=WyomingConnectionPolicy.LOCAL_ONLY),
    )
    await server.start()
    port = server._server._server.sockets[0].getsockname()[1]  # noqa: SLF001

    try:
        async with AsyncTcpClient('127.0.0.1', port) as client:
            await client.write_event(RunSatellite().event())
            await asyncio.sleep(0.1)

            dispatched: list[object] = []
            monkeypatch.setattr(satellite.store, 'dispatch', dispatched.append)

            await server.wake('hey home assistant', 'vosk')
            await _read_until(client, lambda event: AudioStart.is_type(event.type))
            lit = _ring_actions(dispatched, 'RgbRingSetAllAction')
            assert [cast('Any', action).color for action in lit] == [(0, 255, 0)]
            assert not _ring_actions(dispatched, 'RgbRingBlankAction')

            if ending == 'transcript':
                await client.write_event(Transcript(text='lights on').event())
                await _read_until(client, lambda event: AudioStop.is_type(event.type))
            # Otherwise say nothing: the utterance is still live, so closing the
            # socket below is what has to darken the ring.

        # Leaving the context closes the socket, exercising the teardown path.
        for _ in range(20):
            if _ring_actions(dispatched, 'RgbRingBlankAction'):
                break
            await asyncio.sleep(0.05)
        assert _ring_actions(dispatched, 'RgbRingBlankAction')
    finally:
        await server.stop()
