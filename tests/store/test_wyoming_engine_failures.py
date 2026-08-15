"""Termination contract for Wyoming engine requests that cannot be fulfilled.

Home Assistant's speech clients stop reading only on ``transcript`` (STT) and
``audio-stop`` (TTS), ignore ``error`` entirely, and apply no timeout, so a
failure that leaves the connection open hangs Home Assistant forever. The
conversation client is the exception: it accepts ``not-handled`` as terminal.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncTcpClient
from wyoming.error import Error
from wyoming.handle import NotHandled
from wyoming.tts import Synthesize

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

SERVICE_DIR = (
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '090-wyoming'
)
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from security import PeerAccess  # noqa: E402  # type: ignore[reportMissingImports]


class _FailingBridge:
    """Stand in for an assistant whose provider fails or is not running."""

    async def request(
        self,
        action_factory: Any,  # noqa: ANN401, ARG002
        *,
        cancelled: asyncio.Event | None = None,  # noqa: ARG002
    ) -> AsyncIterator[Any]:
        from assistant_bridge import (  # type: ignore[reportMissingImports]
            AssistantBridgeError,
        )

        for _ in range(0):
            yield None  # pragma: no cover - makes this an async generator
        msg = 'Assistant request timed out'
        raise AssistantBridgeError(msg)


@pytest.fixture
def _same_loop_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run response tasks on the loop that owns the sockets, as the service does.

    In the running app a service's coroutine runner and its Wyoming listeners
    share one event loop. Outside a service thread ``create_task`` hands the
    coroutine to the global worker thread instead, so a response would be
    written to the stream from a foreign loop.
    """
    import engines  # type: ignore[reportMissingImports]

    monkeypatch.setattr(
        engines,
        'create_task',
        lambda coroutine: asyncio.get_running_loop().create_task(coroutine),
    )


async def _serve_failing_engines() -> tuple[Any, int]:
    from engines import EnginesServer  # type: ignore[reportMissingImports]

    server = EnginesServer(
        host='127.0.0.1',
        port=0,
        access=PeerAccess(),
        bridge=_FailingBridge(),
    )
    await server.start()
    port = server._server._server.sockets[0].getsockname()[1]  # noqa: SLF001
    return server, port


async def _drain_until_closed(client: AsyncTcpClient) -> list[Any]:
    """Read until the peer closes, so a hang fails the test instead of blocking."""
    events: list[Any] = []
    while True:
        event = await asyncio.wait_for(client.read_event(), timeout=5)
        if event is None:
            return events
        events.append(event)


@pytest.mark.usefixtures('_same_loop_tasks')
@pytest.mark.asyncio
async def test_failed_transcription_reports_an_error_and_closes() -> None:
    """A failed STT request must end, not leave Home Assistant reading forever."""
    server, port = await _serve_failing_engines()
    try:
        async with AsyncTcpClient('127.0.0.1', port) as client:
            await client.write_event(Transcribe().event())
            await client.write_event(
                AudioStart(rate=16000, width=2, channels=1).event(),
            )
            await client.write_event(
                AudioChunk(
                    rate=16000,
                    width=2,
                    channels=1,
                    audio=b'\x00\x00' * 160,
                ).event(),
            )
            await client.write_event(AudioStop().event())

            events = await _drain_until_closed(client)

        assert any(Error.is_type(event.type) for event in events)
        assert not any(Transcript.is_type(event.type) for event in events)
    finally:
        await server.stop()


@pytest.mark.usefixtures('_same_loop_tasks')
@pytest.mark.asyncio
async def test_failed_synthesis_reports_an_error_and_closes() -> None:
    """A failed TTS request must end rather than stall the Home Assistant read."""
    server, port = await _serve_failing_engines()
    try:
        async with AsyncTcpClient('127.0.0.1', port) as client:
            await client.write_event(Synthesize(text='hello').event())

            events = await _drain_until_closed(client)

        assert any(Error.is_type(event.type) for event in events)
        assert not any(AudioStop.is_type(event.type) for event in events)
    finally:
        await server.stop()


@pytest.mark.usefixtures('_same_loop_tasks')
@pytest.mark.asyncio
async def test_failed_conversation_answers_not_handled() -> None:
    """The conversation client terminates on ``not-handled``, never on ``error``."""
    server, port = await _serve_failing_engines()
    try:
        async with AsyncTcpClient('127.0.0.1', port) as client:
            await client.write_event(Transcript(text='turn on the lights').event())

            event = await asyncio.wait_for(client.read_event(), timeout=5)

        assert event is not None
        assert NotHandled.is_type(event.type)
    finally:
        await server.stop()


@pytest.mark.usefixtures('_same_loop_tasks')
@pytest.mark.asyncio
async def test_oversized_conversation_text_answers_not_handled() -> None:
    """Rejected conversation input still terminates the Home Assistant request."""
    server, port = await _serve_failing_engines()
    try:
        async with AsyncTcpClient('127.0.0.1', port) as client:
            await client.write_event(Transcript(text='x' * 20_000).event())

            event = await asyncio.wait_for(client.read_event(), timeout=5)

        assert event is not None
        assert NotHandled.is_type(event.type)
    finally:
        await server.stop()


@pytest.mark.usefixtures('_same_loop_tasks')
@pytest.mark.asyncio
async def test_malformed_asr_audio_reports_an_error_and_closes() -> None:
    """An unsupported input format fails the request instead of buffering it."""
    server, port = await _serve_failing_engines()
    try:
        async with AsyncTcpClient('127.0.0.1', port) as client:
            await client.write_event(Transcribe().event())
            await client.write_event(
                AudioStart(rate=16000, width=4, channels=1).event(),
            )

            events = await _drain_until_closed(client)

        assert any(Error.is_type(event.type) for event in events)
        assert not any(Transcript.is_type(event.type) for event in events)
    finally:
        await server.stop()
