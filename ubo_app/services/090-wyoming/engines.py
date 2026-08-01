"""Wyoming ASR, TTS, and conversation handlers over Ubo assistant requests."""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from assistant_bridge import (
    AssistantBridge,
    AssistantBridgeCancelledError,
    AssistantBridgeError,
)
from constants import (
    MAX_ASR_AUDIO_BYTES,
    MAX_AUDIO_CHANNELS,
    MAX_AUDIO_RATE,
    MAX_ENGINE_REQUESTS,
    MIN_AUDIO_RATE,
    PCM_WIDTH_BYTES,
)
from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.error import Error
from wyoming.handle import Handled, NotHandled
from wyoming.info import (
    AsrModel,
    AsrProgram,
    Attribution,
    Describe,
    HandleModel,
    HandleProgram,
    Info,
    TtsProgram,
    TtsVoice,
)
from wyoming.ping import Ping, Pong
from wyoming.server import AsyncEventHandler, AsyncTcpServer
from wyoming.tts import Synthesize

from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.assistant import (
    AssistanceAudioFrame,
    AssistanceTextFrame,
    AssistantCompleteAction,
    AssistantState,
    AssistantSynthesizeAction,
    AssistantTranscribeAction,
)
from ubo_app.store.services.wyoming import (
    WyomingEnginesStatus,
    WyomingReportEnginesStatusAction,
)
from ubo_app.utils.async_ import create_task

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from security import PeerAccess
    from wyoming.event import Event

_ATTRIBUTION = Attribution(name='Ubo', url='https://getubo.com')
_MAX_TEXT_LENGTH = 16_384


class EngineRequestCancelledError(RuntimeError):
    """A disconnected engine client no longer wants its queued request."""


@dataclass(frozen=True)
class _AsrFormat:
    """Validated input PCM format accepted by the one-shot assistant pipeline."""

    rate: int
    channels: int


def _build_info() -> Info:
    """Advertise the currently selected Ubo engines with complete metadata."""
    # Read the persisted selection rather than the live store. This description
    # handler is valid even while service reducers are still registering at boot.
    state = AssistantState()
    selected_stt = state.selected_stt.value
    selected_llm = state.selected_llm.value
    selected_tts = state.selected_tts.value
    voice = state.selected_voices.get(state.selected_tts, '')
    if not voice:
        voice = state.selected_piper_voice

    asr_model = AsrModel(
        name=selected_stt,
        attribution=_ATTRIBUTION,
        installed=True,
        description='Selected Ubo speech recognition engine',
        version=None,
        languages=['en'],
    )
    tts_voice = TtsVoice(
        name=voice or selected_tts,
        attribution=_ATTRIBUTION,
        installed=True,
        description='Selected Ubo speech synthesis voice',
        version=None,
        languages=['en'],
    )
    handle_model = HandleModel(
        name=selected_llm,
        attribution=_ATTRIBUTION,
        installed=True,
        description='Selected Ubo language model',
        version=None,
        languages=['en'],
    )
    return Info(
        asr=[
            AsrProgram(
                name='ubo-asr',
                attribution=_ATTRIBUTION,
                installed=True,
                description='Ubo assistant speech recognition',
                version=None,
                models=[asr_model],
                requires_external_vad=True,
            ),
        ],
        tts=[
            TtsProgram(
                name='ubo-tts',
                attribution=_ATTRIBUTION,
                installed=True,
                description='Ubo assistant speech synthesis',
                version=None,
                voices=[tts_voice],
            ),
        ],
        handle=[
            HandleProgram(
                name='ubo-handle',
                attribution=_ATTRIBUTION,
                installed=True,
                description='One-turn Ubo language-model conversation agent',
                version=None,
                models=[handle_model],
                supports_handled_streaming=False,
                supports_home_control=False,
            ),
        ],
    )


class _RejectedEnginesHandler(AsyncEventHandler):
    """Close unauthorized clients before they can invoke costly providers."""

    async def handle_event(self, event: Event) -> bool:
        """Reject the first received event without inspecting its contents."""
        del event
        return False


class EnginesEventHandler(AsyncEventHandler):
    """Handle one Wyoming ASR, TTS, or conversation request connection."""

    def __init__(self, *args: object, server: EnginesServer) -> None:
        """Initialize request-local buffers and serialized response writes."""
        super().__init__(*args)  # type: ignore[arg-type]
        self._server = server
        self._write_lock = asyncio.Lock()
        self._asr_requested = False
        self._asr_format: _AsrFormat | None = None
        self._asr_audio = bytearray()
        self._in_flight = False
        self._request_cancel: asyncio.Event | None = None

    async def send(self, event: Event) -> None:
        """Keep asynchronous assistant responses ordered on the TCP stream."""
        async with self._write_lock:
            await self.write_event(event)

    async def _fail(self, *, text: str, code: str) -> None:
        """End an ASR or TTS request that cannot produce its terminal event.

        Home Assistant's speech clients only stop reading on ``transcript`` and
        ``audio-stop``; they ignore ``error`` and apply no timeout. Closing the
        connection is what turns a failure into a failed request there instead
        of one that blocks forever.
        """
        with contextlib.suppress(ConnectionError, OSError):
            await self.send(Error(text=text, code=code).event())
        await self.stop()

    async def handle_event(self, event: Event) -> bool:
        """Dispatch a request without blocking ping/connection processing."""
        if Describe.is_type(event.type):
            await self.send(_build_info().event())
            return True
        if Ping.is_type(event.type):
            ping = Ping.from_event(event)
            await self.send(Pong(text=ping.text).event())
            return True
        if Transcribe.is_type(event.type):
            await self._begin_asr()
            return True
        if AudioStart.is_type(event.type):
            await self._begin_audio(AudioStart.from_event(event))
            return True
        if AudioChunk.is_type(event.type):
            await self._append_audio(AudioChunk.from_event(event))
            return True
        if AudioStop.is_type(event.type):
            await self._finish_audio()
            return True
        if Synthesize.is_type(event.type):
            synthesize = Synthesize.from_event(event)
            await self._start_synthesis(synthesize.text)
            return True
        if Transcript.is_type(event.type):
            transcript = Transcript.from_event(event)
            await self._start_handle(transcript.text)
        return True

    async def _begin_asr(self) -> None:
        if self._in_flight:
            await self._fail(text='Request already in progress', code='busy')
            return
        self._asr_requested = True
        self._asr_format = None
        self._asr_audio.clear()

    async def _begin_audio(self, audio: AudioStart) -> None:
        if not self._asr_requested:
            await self._fail(text='Expected transcribe before audio', code='sequence')
            return
        if (
            audio.width != PCM_WIDTH_BYTES
            or not MIN_AUDIO_RATE <= audio.rate <= MAX_AUDIO_RATE
            or not 1 <= audio.channels <= MAX_AUDIO_CHANNELS
        ):
            self._asr_requested = False
            await self._fail(text='Unsupported ASR audio format', code='format')
            return
        self._asr_format = _AsrFormat(rate=audio.rate, channels=audio.channels)

    async def _append_audio(self, chunk: AudioChunk) -> None:
        if self._asr_format is None:
            return
        if (
            chunk.width != PCM_WIDTH_BYTES
            or chunk.rate != self._asr_format.rate
            or chunk.channels != self._asr_format.channels
            or len(chunk.audio) % (PCM_WIDTH_BYTES * chunk.channels) != 0
        ):
            self._asr_requested = False
            self._asr_format = None
            self._asr_audio.clear()
            await self._fail(text='ASR audio format changed mid-stream', code='format')
            return
        if len(self._asr_audio) + len(chunk.audio) > MAX_ASR_AUDIO_BYTES:
            self._asr_requested = False
            self._asr_format = None
            self._asr_audio.clear()
            await self._fail(text='ASR audio stream is too large', code='limit')
            return
        self._asr_audio.extend(chunk.audio)

    async def _finish_audio(self) -> None:
        if not self._asr_requested or self._asr_format is None:
            return
        audio = bytes(self._asr_audio)
        audio_format = self._asr_format
        self._asr_requested = False
        self._asr_format = None
        self._asr_audio.clear()
        if not audio:
            await self._fail(text='No ASR audio received', code='audio')
            return
        cancelled = self._begin_request()
        create_task(self._respond_asr(audio, audio_format, cancelled))

    async def _start_synthesis(self, text: str) -> None:
        rejection = self._text_request_rejection(text)
        if rejection is not None:
            await self._fail(text=rejection, code='request')
            return
        cancelled = self._begin_request()
        create_task(self._respond_tts(text, cancelled))

    async def _start_handle(self, text: str) -> None:
        rejection = self._text_request_rejection(text)
        if rejection is not None:
            # ``not-handled`` is the conversation client's terminal event; an
            # ``error`` would leave Home Assistant reading forever.
            await self.send(NotHandled(text=rejection).event())
            return
        cancelled = self._begin_request()
        create_task(self._respond_handle(text, cancelled))

    def _text_request_rejection(self, text: str) -> str | None:
        if self._in_flight:
            return 'Request already in progress'
        if not text or len(text) > _MAX_TEXT_LENGTH:
            return 'Invalid request text'
        return None

    def _begin_request(self) -> asyncio.Event:
        """Create the cancellation signal shared by one response task."""
        self._in_flight = True
        self._request_cancel = asyncio.Event()
        return self._request_cancel

    def _finish_request(self, cancelled: asyncio.Event) -> None:
        """Clear request-local state without disrupting a replacement request."""
        if self._request_cancel is cancelled:
            self._request_cancel = None
        self._in_flight = False

    async def _respond_asr(
        self,
        audio: bytes,
        audio_format: _AsrFormat,
        cancelled: asyncio.Event,
    ) -> None:
        try:
            async with self._server.request_slot(cancelled):
                transcript = ''
                async for frame in self._server.bridge.request(
                    lambda session_id: AssistantTranscribeAction(
                        audio=audio,
                        session_id=session_id,
                        sample_rate=audio_format.rate,
                        num_channels=audio_format.channels,
                    ),
                    cancelled=cancelled,
                ):
                    if isinstance(frame, AssistanceTextFrame) and frame.text:
                        # STT providers may emit revisions; the final non-empty
                        # frame is the usable transcript, never concatenation.
                        transcript = frame.text
                await self.send(Transcript(text=transcript).event())
        except (AssistantBridgeCancelledError, EngineRequestCancelledError):
            return
        except AssistantBridgeError as error:
            await self._fail(text=str(error), code='assistant')
        finally:
            self._finish_request(cancelled)

    async def _respond_tts(self, text: str, cancelled: asyncio.Event) -> None:
        audio_started = False
        try:
            async with self._server.request_slot(cancelled):
                async for frame in self._server.bridge.request(
                    lambda session_id: AssistantSynthesizeAction(
                        text=text,
                        session_id=session_id,
                    ),
                    cancelled=cancelled,
                ):
                    if (
                        not isinstance(frame, AssistanceAudioFrame)
                        or frame.audio is None
                    ):
                        continue
                    sample = frame.audio
                    if not audio_started:
                        await self.send(
                            AudioStart(
                                rate=sample.rate,
                                width=sample.width,
                                channels=sample.channels,
                            ).event(),
                        )
                        audio_started = True
                    await self.send(
                        AudioChunk(
                            rate=sample.rate,
                            width=sample.width,
                            channels=sample.channels,
                            audio=sample.data,
                        ).event(),
                    )
                if not audio_started:
                    await self._fail(text='No synthesized audio produced', code='audio')
                    return
                await self.send(AudioStop().event())
        except (AssistantBridgeCancelledError, EngineRequestCancelledError):
            return
        except AssistantBridgeError as error:
            # Half-streamed audio cannot be completed with ``audio-stop``
            # without Home Assistant speaking a truncated response as if it
            # were whole, so fail the connection either way.
            await self._fail(text=str(error), code='assistant')
        finally:
            self._finish_request(cancelled)

    async def _respond_handle(self, text: str, cancelled: asyncio.Event) -> None:
        try:
            async with self._server.request_slot(cancelled):
                response_chunks = [
                    frame.text
                    async for frame in self._server.bridge.request(
                        lambda session_id: AssistantCompleteAction(
                            text=text,
                            session_id=session_id,
                            enable_tools=False,
                        ),
                        cancelled=cancelled,
                    )
                    if isinstance(frame, AssistanceTextFrame) and frame.text
                ]
                await self.send(Handled(text=''.join(response_chunks)).event())
        except (AssistantBridgeCancelledError, EngineRequestCancelledError):
            return
        except AssistantBridgeError as error:
            # HA's conversation client treats NotHandled as terminal; Error is
            # not a terminal conversation result for this protocol path.
            await self.send(NotHandled(text=str(error)).event())
        finally:
            self._finish_request(cancelled)

    async def disconnect(self) -> None:
        """Discard buffered unstarted audio when the client disconnects."""
        self._asr_requested = False
        self._asr_format = None
        self._asr_audio.clear()
        if self._request_cancel is not None:
            self._request_cancel.set()


class EnginesServer:
    """Bounded multi-client Wyoming server for Ubo's one-shot engines."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        access: PeerAccess,
        bridge: AssistantBridge,
    ) -> None:
        """Initialize a bounded listener for all one-shot engine connections."""
        self._server = AsyncTcpServer(host, port)
        self._access = access
        self.bridge = bridge
        self._requests = asyncio.Semaphore(MAX_ENGINE_REQUESTS)
        self._active_requests = 0
        self._is_started = False

    async def start(self) -> None:
        """Start accepting only policy-authorized engine clients."""
        await self._server.start(self._create_handler)
        self._is_started = True
        self._report_status()

    async def stop(self) -> None:
        """Stop all engine clients and release their listening socket."""
        self._is_started = False
        await self._server.stop()
        store.dispatch(
            WyomingReportEnginesStatusAction(
                status=WyomingEnginesStatus.STOPPED,
                active_requests=0,
            ),
        )

    @asynccontextmanager
    async def request_slot(self, cancelled: asyncio.Event) -> AsyncIterator[None]:
        """Bound expensive assistant work across all allowed TCP clients."""
        while True:
            if cancelled.is_set():
                raise EngineRequestCancelledError
            try:
                await asyncio.wait_for(self._requests.acquire(), timeout=0.25)
            except TimeoutError:
                continue
            if cancelled.is_set():
                self._requests.release()
                raise EngineRequestCancelledError
            break
        self._active_requests += 1
        self._report_status()
        try:
            yield
        finally:
            self._requests.release()
            self._active_requests -= 1
            self._report_status()

    def _report_status(self) -> None:
        store.dispatch(
            WyomingReportEnginesStatusAction(
                status=(
                    WyomingEnginesStatus.STOPPED
                    if not self._is_started
                    else (
                        WyomingEnginesStatus.BUSY
                        if self._active_requests
                        else WyomingEnginesStatus.LISTENING
                    )
                ),
                active_requests=self._active_requests,
            ),
        )

    def _create_handler(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> AsyncEventHandler:
        peer_name = writer.get_extra_info('peername')
        peer = peer_name[0] if isinstance(peer_name, tuple) and peer_name else ''
        if not self._access.allows(peer):
            logger.warning('Rejected unauthorized Wyoming engines peer %s', peer)
            writer.close()
            return _RejectedEnginesHandler(reader, writer)
        return EnginesEventHandler(reader, writer, server=self)
