"""Wire-level smoke test for the local Wyoming satellite listener."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterable
from wyoming.client import AsyncTcpClient
from wyoming.info import Describe, Info
from wyoming.ping import Ping, Pong

from ubo_app.store.services.wyoming import WyomingConnectionPolicy

SERVICE_DIR = (
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '090-wyoming'
)
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from security import PeerAccess  # noqa: E402  # type: ignore[reportMissingImports]


class _DiscardingWriter:
    """Accept the handler's protocol writes without a socket behind them."""

    def write(self, data: bytes) -> None:
        """Drop the encoded event."""

    def writelines(self, data: Iterable[bytes]) -> None:
        """Drop the encoded event header and payload."""

    async def drain(self) -> None:
        """Report the imaginary socket as always flushed."""

    def close(self) -> None:
        """Match the stream-writer interface used on teardown."""


class _InertServer:
    """Satisfy the handler's server collaborator without a listener."""

    async def activate(self, handler: object) -> None:
        """Accept the session without tracking it."""

    async def disconnect(self, handler: object) -> None:
        """Accept the teardown without tracking it."""


@pytest.mark.asyncio
async def test_satellite_describe_and_ping_round_trip() -> None:
    """Home Assistant can discover the safe local listener and keep it alive."""
    from satellite import SatelliteServer  # type: ignore[reportMissingImports]

    server = SatelliteServer(
        host='127.0.0.1',
        port=0,
        access=PeerAccess(policy=WyomingConnectionPolicy.LOCAL_ONLY),
    )
    await server.start()
    socket = server._server._server.sockets[0]  # noqa: SLF001
    port = socket.getsockname()[1]

    try:
        async with AsyncTcpClient('127.0.0.1', port) as client:
            await client.write_event(Describe().event())
            response = await asyncio.wait_for(client.read_event(), timeout=1)
            assert response is not None
            assert Info.is_type(response.type)
            info = Info.from_event(response)
            assert info.satellite is not None
            assert info.satellite.installed

            await client.write_event(Ping(text='healthcheck').event())
            response = await asyncio.wait_for(client.read_event(), timeout=1)
            assert response is not None
            assert Pong.is_type(response.type)
            assert Pong.from_event(response).text == 'healthcheck'
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_pause_stops_streaming_without_dropping_the_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``pause-satellite`` must pause the stream, not end the session.

    Driven over a real socket on purpose: the flag that pauses streaming lives
    next to the base handler's read-loop condition, and only the live loop can
    show that pausing left the connection usable.
    """
    import satellite  # type: ignore[reportMissingImports]
    from satellite import SatelliteServer  # type: ignore[reportMissingImports]
    from wyoming.satellite import PauseSatellite, RunSatellite

    # The service-context coroutine runner does not exist under bare pytest.
    monkeypatch.setattr(
        satellite,
        'create_task',
        lambda coroutine, *_args, **_kwargs: asyncio.get_running_loop().create_task(
            coroutine,
        ),
    )

    server = SatelliteServer(
        host='127.0.0.1',
        port=0,
        access=PeerAccess(policy=WyomingConnectionPolicy.LOCAL_ONLY),
    )
    await server.start()
    socket = server._server._server.sockets[0]  # noqa: SLF001
    port = socket.getsockname()[1]

    try:
        async with AsyncTcpClient('127.0.0.1', port) as client:
            await client.write_event(RunSatellite().event())
            await client.write_event(PauseSatellite().event())
            await client.write_event(Ping(text='after-pause').event())

            while True:
                response = await asyncio.wait_for(client.read_event(), timeout=2)
                # ``None`` is the disconnect this test exists to catch.
                assert response is not None, 'connection closed after pause-satellite'
                if Pong.is_type(response.type):
                    assert Pong.from_event(response).text == 'after-pause'
                    break

            assert server._active is not None  # noqa: SLF001
            # ``_is_armed`` — not ``is_running`` — is the flag ``pause-satellite``
            # clears; ``is_running`` is false between utterances anyway, so it
            # would pass here even if the pause had been ignored.
            assert not server._active._is_armed  # noqa: SLF001
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_each_utterance_uses_a_fresh_audio_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stranded playback must not wedge every later Home Assistant response.

    The audio manager keys its buffer by sequence id and anchors playback to the
    first index it sees, so reusing one id across utterances would leave a later
    utterance's chunks sitting behind the head index of an earlier one that
    never drained.
    """
    import satellite  # type: ignore[reportMissingImports]
    from satellite import SatelliteEventHandler  # type: ignore[reportMissingImports]
    from wyoming.audio import AudioChunk, AudioStart

    from ubo_app.store.services.audio import AudioPlayAudioSequenceAction

    dispatched: list[object] = []
    monkeypatch.setattr(satellite.store, 'dispatch', dispatched.append)

    handler = SatelliteEventHandler(
        asyncio.StreamReader(),
        _DiscardingWriter(),
        server=_InertServer(),
        peer='127.0.0.1',
    )

    async def play_one_utterance() -> str:
        await handler._start_tts(  # noqa: SLF001
            AudioStart(rate=48_000, width=2, channels=1),
        )
        await handler._play_tts_chunk(  # noqa: SLF001
            AudioChunk(rate=48_000, width=2, channels=1, audio=b'\x00\x00' * 480),
        )
        sequence = next(
            action
            for action in reversed(dispatched)
            if isinstance(action, AudioPlayAudioSequenceAction)
        )
        # The audio never reports completion, so this stands in for a playback
        # that timed out with its buffer still held by the audio manager.
        await handler._finish_playback()  # noqa: SLF001
        return sequence.id

    first = await play_one_utterance()
    second = await play_one_utterance()

    assert first != second


@pytest.mark.asyncio
async def test_engines_listener_answers_ping_without_starting_a_pipeline() -> None:
    """The shared ASR/TTS/conversation port supports Wyoming health checks."""
    from assistant_bridge import AssistantBridge  # type: ignore[reportMissingImports]
    from engines import EnginesServer  # type: ignore[reportMissingImports]

    server = EnginesServer(
        host='127.0.0.1',
        port=0,
        access=PeerAccess(policy=WyomingConnectionPolicy.LOCAL_ONLY),
        bridge=AssistantBridge(),
    )
    await server.start()
    socket = server._server._server.sockets[0]  # noqa: SLF001
    port = socket.getsockname()[1]

    try:
        async with AsyncTcpClient('127.0.0.1', port) as client:
            await client.write_event(Describe().event())
            response = await asyncio.wait_for(client.read_event(), timeout=1)
            assert response is not None
            assert Info.is_type(response.type)
            info = Info.from_event(response)
            assert info.asr
            assert info.tts
            assert info.handle

            await client.write_event(Ping(text='healthcheck').event())
            response = await asyncio.wait_for(client.read_event(), timeout=1)
            assert response is not None
            assert Pong.is_type(response.type)
            assert Pong.from_event(response).text == 'healthcheck'
    finally:
        await server.stop()
