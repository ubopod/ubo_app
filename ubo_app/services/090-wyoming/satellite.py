"""Wyoming satellite listener backed by Ubo's microphone and speaker services."""

from __future__ import annotations

import asyncio
import contextlib
import socket
import uuid
from typing import TYPE_CHECKING

import numpy as np
import soxr
from constants import (
    MAX_AUDIO_CHANNELS,
    MAX_AUDIO_RATE,
    MAX_TTS_AUDIO_BYTES,
    MAX_UTTERANCE_SECONDS,
    MIN_AUDIO_RATE,
    PCM_WIDTH_BYTES,
    PLAYBACK_DONE_TIMEOUT_SECONDS,
    SATELLITE_MIC_QUEUE_SIZE,
)
from wyoming.asr import Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.error import Error
from wyoming.info import Attribution, Describe, Info, Satellite
from wyoming.ping import Ping, Pong
from wyoming.pipeline import PipelineStage, RunPipeline
from wyoming.satellite import PauseSatellite, RunSatellite
from wyoming.server import AsyncEventHandler, AsyncTcpServer
from wyoming.snd import Played
from wyoming.vad import VoiceStopped
from wyoming.wake import Detection

from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.audio import (
    AudioPlayAudioSequenceAction,
    AudioPlaybackDoneEvent,
    AudioPlayChimeAction,
    AudioSample,
)
from ubo_app.store.services.rgb_ring import (
    RgbRingBlankAction,
    RgbRingSetAllAction,
)
from ubo_app.store.services.wyoming import (
    WyomingReportSatelliteStatusAction,
    WyomingSatelliteStatus,
)
from ubo_app.utils.async_ import create_task

if TYPE_CHECKING:
    from security import PeerAccess
    from wyoming.event import Event

_ATTRIBUTION = Attribution(name='Ubo', url='https://getubo.com')
_TARGET_RATE = 48_000
# Lit while a command is being streamed to Home Assistant. Distinct from the blue
# the on-device voice-shortcut listener uses, so the ring says which one is
# listening.
_LISTENING_COLOR = (0, 255, 0)


def _satellite_info() -> Info:
    """Build fully populated Wyoming metadata for the Ubo satellite."""
    return Info(
        satellite=Satellite(
            name=socket.gethostname(),
            attribution=_ATTRIBUTION,
            installed=True,
            description='Ubo Pod satellite',
            version=None,
            has_vad=False,
            supports_trigger=False,
        ),
    )


class _RejectedSatelliteHandler(AsyncEventHandler):
    """Close unauthorized connections before they can request microphone audio."""

    async def handle_event(self, event: Event) -> bool:
        """Reject the first received event without inspecting its contents."""
        del event
        return False


class SatelliteEventHandler(AsyncEventHandler):
    """One authenticated Wyoming satellite connection."""

    def __init__(self, *args: object, server: SatelliteServer, peer: str) -> None:
        """Initialize a bounded microphone queue and local playback state."""
        super().__init__(*args)  # type: ignore[arg-type]
        self._server = server
        self._peer = peer
        self._mic_queue: asyncio.Queue[bytes | None] = asyncio.Queue(
            maxsize=SATELLITE_MIC_QUEUE_SIZE,
        )
        self._outbound_lock = asyncio.Lock()
        # Never name either of these ``_is_running``: the base handler owns that
        # attribute as its read-loop condition, so clearing it to stop streaming
        # would terminate the connection instead of pausing it.
        #
        # ``_is_armed``  — Home Assistant sent ``run-satellite`` and will accept
        #                  pipeline runs (cleared by ``pause-satellite``).
        # ``_is_speaking`` — a local wake word fired and we are inside one
        #                  utterance. The microphone is forwarded only then, so
        #                  audio leaves the device only between a wake word and
        #                  the end of the command that followed it.
        self._is_armed = False
        self._is_speaking = False
        self._utterance_timeout: asyncio.TimerHandle | None = None
        self._is_playing = False
        self._writer_started = False
        # Minted per utterance in ``_start_tts``: a sequence id shared across
        # utterances would collide with the audio manager's buffer for the
        # previous one whenever that buffer outlives its playback (e.g. after
        # ``PLAYBACK_DONE_TIMEOUT_SECONDS``), stranding every later utterance
        # behind a head index it can never reach.
        self._sequence_id = ''
        self._sequence_index = 0
        self._playback_done = asyncio.Event()
        self._tts_rate: int | None = None
        self._tts_channels: int | None = None
        self._tts_resampler: soxr.ResampleStream | None = None
        self._tts_remainder = b''
        self._received_tts_bytes = 0
        self._has_tts_audio = False
        self._is_receiving_tts = False

    @property
    def is_running(self) -> bool:
        """Whether this handler currently forwards microphone audio."""
        return self._is_armed and self._is_speaking and not self._is_playing

    async def send(self, event: Event) -> None:
        """Serialize writes from microphone, playback, and ping tasks."""
        async with self._outbound_lock:
            await self.write_event(event)

    async def enqueue_microphone(self, sample: bytes) -> None:
        """Evict stale audio rather than accumulating latency under a slow peer."""
        if not self.is_running:
            return
        if self._mic_queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._mic_queue.get_nowait()
        with contextlib.suppress(asyncio.QueueFull):
            self._mic_queue.put_nowait(sample)

    async def notify_playback_done(self, sequence_id: str) -> None:
        """Release a pending Wyoming ``played`` acknowledgement."""
        if self._sequence_id and sequence_id == self._sequence_id:
            self._playback_done.set()

    async def handle_event(self, event: Event) -> bool:
        """Handle satellite protocol events without blocking the read loop."""
        await self._server.activate(self)
        if await self._handle_tts_event(event):
            return True
        if Describe.is_type(event.type):
            await self.send(_satellite_info().event())
            return True
        if Ping.is_type(event.type):
            ping = Ping.from_event(event)
            await self.send(Pong(text=ping.text).event())
            return True
        if RunSatellite.is_type(event.type):
            await self._arm()
            return True
        if PauseSatellite.is_type(event.type):
            self._is_armed = False
            await self._end_utterance()
            store.dispatch(
                WyomingReportSatelliteStatusAction(
                    status=WyomingSatelliteStatus.PAUSED,
                    client=self._peer,
                ),
            )
            return True
        if Detection.is_type(event.type):
            store.dispatch(AudioPlayChimeAction(name='ready'))
            return True
        if VoiceStopped.is_type(event.type) or Transcript.is_type(event.type):
            # Home Assistant reached the end of the command: its voice-activity
            # detector saw silence, or speech-to-text finished (the only one of
            # the two a provider that endpoints internally is guaranteed to
            # send). Either way the microphone is no longer wanted.
            await self._end_utterance()
            return True
        if Error.is_type(event.type):
            error = Error.from_event(event)
            logger.warning('Wyoming satellite error: %s', error.text)
            # A run that failed (e.g. a misconfigured pipeline) never reaches
            # `transcript` or a response, so release the microphone here rather
            # than holding it until the utterance timeout.
            await self._end_utterance()
        return True

    async def _handle_tts_event(self, event: Event) -> bool:
        """Consume the inbound response-audio stream. Returns whether it did."""
        if AudioStart.is_type(event.type):
            await self._start_tts(AudioStart.from_event(event))
            return True
        if AudioChunk.is_type(event.type):
            await self._play_tts_chunk(AudioChunk.from_event(event))
            return True
        if AudioStop.is_type(event.type):
            await self._finish_tts_input()
            return True
        return False

    async def disconnect(self) -> None:
        """Stop forwarding and detach this connection on socket teardown."""
        self._is_armed = False
        self._stop_speaking()
        self._is_playing = False
        with contextlib.suppress(asyncio.QueueFull):
            self._mic_queue.put_nowait(None)
        await self._server.disconnect(self)

    async def _arm(self) -> None:
        """Accept pipeline runs without yet sending any microphone audio.

        The wake word is detected on-device, so Home Assistant is only asked to
        run a pipeline once one fires. That keeps its ``wake`` stage — and the
        wake-word engine it would need — out of the picture entirely, and the
        microphone off the network between commands.
        """
        self._is_armed = True
        if not self._writer_started:
            self._writer_started = True
            create_task(self._write_microphone())
        store.dispatch(
            WyomingReportSatelliteStatusAction(
                status=WyomingSatelliteStatus.CONNECTED,
                client=self._peer,
            ),
        )

    async def wake(self, phrase: str, detector: str) -> None:
        """Start one Home Assistant pipeline run after a local wake word."""
        if not self._is_armed or self._is_speaking or self._is_playing:
            logger.info(
                'Ignoring a Home Assistant wake word',
                extra={
                    'is_armed': self._is_armed,
                    'is_speaking': self._is_speaking,
                    'is_playing': self._is_playing,
                },
            )
            return
        logger.info(
            'Handing a wake word to Home Assistant',
            extra={'phrase': phrase, 'detector': detector, 'peer': self._peer},
        )
        self._is_speaking = True
        store.dispatch(RgbRingSetAllAction(color=_LISTENING_COLOR))
        await self.send(Detection(name=phrase or detector).event())
        # Starting at ASR (not WAKE) is what frees Home Assistant from needing a
        # wake-word engine — it only validates one for a WAKE-stage run. No
        # restart-on-end either: the next run comes from the next local wake.
        await self.send(
            RunPipeline(
                start_stage=PipelineStage.ASR,
                end_stage=PipelineStage.TTS,
                restart_on_end=False,
            ).event(),
        )
        await self.send(
            AudioStart(rate=16_000, width=PCM_WIDTH_BYTES, channels=1).event(),
        )
        self._utterance_timeout = asyncio.get_running_loop().call_later(
            MAX_UTTERANCE_SECONDS,
            lambda: create_task(self._end_utterance()),
        )
        store.dispatch(
            WyomingReportSatelliteStatusAction(
                status=WyomingSatelliteStatus.STREAMING,
                client=self._peer,
            ),
        )

    def _stop_speaking(self) -> bool:
        """Leave the utterance and darken its indicator. Returns whether it did.

        Every exit from an utterance funnels through here — end of command, error,
        timeout, pause, socket teardown — so the ring can never be left lit with
        nothing listening.
        """
        if not self._is_speaking:
            return False
        self._is_speaking = False
        self._cancel_utterance_timeout()
        store.dispatch(RgbRingBlankAction())
        return True

    async def _end_utterance(self) -> None:
        """Stop forwarding the microphone and close the audio stream."""
        if not self._stop_speaking():
            return
        with contextlib.suppress(ConnectionError, OSError):
            await self.send(AudioStop().event())
        if self._is_armed and not self._is_playing:
            store.dispatch(
                WyomingReportSatelliteStatusAction(
                    status=WyomingSatelliteStatus.CONNECTED,
                    client=self._peer,
                ),
            )

    def _cancel_utterance_timeout(self) -> None:
        if self._utterance_timeout is not None:
            self._utterance_timeout.cancel()
            self._utterance_timeout = None

    async def _write_microphone(self) -> None:
        """Drain queued mic samples until the handler is disconnected."""
        while True:
            sample = await self._mic_queue.get()
            if sample is None:
                return
            if not self.is_running:
                continue
            try:
                await self.send(
                    AudioChunk(
                        rate=16_000,
                        width=PCM_WIDTH_BYTES,
                        channels=1,
                        audio=sample,
                    ).event(),
                )
            except (ConnectionError, OSError):
                return

    async def _start_tts(self, audio: AudioStart) -> None:
        if self._is_playing:
            await self.send(Error(text='Already playing audio', code='busy').event())
            return
        # Home Assistant reached the response, so the command is over even if
        # neither `voice-stopped` nor `transcript` arrived (e.g. an announcement,
        # or a pipeline that skipped speech-to-text).
        await self._end_utterance()
        if (
            audio.width != PCM_WIDTH_BYTES
            or not 1 <= audio.channels <= MAX_AUDIO_CHANNELS
            or not MIN_AUDIO_RATE <= audio.rate <= MAX_AUDIO_RATE
        ):
            await self.send(
                Error(text='Unsupported TTS audio format', code='format').event(),
            )
            return
        self._is_playing = True
        self._tts_rate = audio.rate
        self._tts_channels = audio.channels
        self._tts_resampler = (
            None
            if audio.rate == _TARGET_RATE
            else soxr.ResampleStream(
                audio.rate,
                _TARGET_RATE,
                audio.channels,
                dtype='float32',
            )
        )
        self._tts_remainder = b''
        self._received_tts_bytes = 0
        self._has_tts_audio = False
        self._is_receiving_tts = True
        self._sequence_id = f'wyoming:satellite:{uuid.uuid4().hex}'
        self._sequence_index = 0
        self._playback_done.clear()
        store.dispatch(
            WyomingReportSatelliteStatusAction(
                status=WyomingSatelliteStatus.PLAYING,
                client=self._peer,
            ),
        )

    async def _play_tts_chunk(self, chunk: AudioChunk) -> None:
        if (
            not self._is_playing
            or not self._is_receiving_tts
            or self._tts_rate is None
            or self._tts_channels is None
        ):
            return
        if (
            chunk.rate != self._tts_rate
            or chunk.width != PCM_WIDTH_BYTES
            or chunk.channels != self._tts_channels
        ):
            await self._abort_tts(
                text='TTS audio format changed mid-stream',
                code='format',
            )
            return
        self._received_tts_bytes += len(chunk.audio)
        if self._received_tts_bytes > MAX_TTS_AUDIO_BYTES:
            await self._abort_tts(
                text='TTS audio stream is too large',
                code='limit',
            )
            return
        audio = self._resample(chunk.audio)
        if not audio:
            return
        self._has_tts_audio = True
        store.dispatch(
            AudioPlayAudioSequenceAction(
                sample=AudioSample(
                    data=audio,
                    rate=_TARGET_RATE,
                    channels=self._tts_channels,
                    width=PCM_WIDTH_BYTES,
                ),
                id=self._sequence_id,
                index=self._sequence_index,
            ),
        )
        self._sequence_index += 1

    def _resample(self, audio: bytes) -> bytes:
        """Convert a complete int16 PCM frame stream to the Ubo output rate."""
        if self._tts_channels is None:
            return b''
        sample_bytes = PCM_WIDTH_BYTES * self._tts_channels
        buffer = self._tts_remainder + audio
        aligned = len(buffer) - len(buffer) % sample_bytes
        self._tts_remainder = buffer[aligned:]
        if aligned == 0:
            return b''
        aligned_audio = buffer[:aligned]
        if self._tts_resampler is None:
            return aligned_audio
        pcm = np.frombuffer(aligned_audio, dtype=np.int16).reshape(
            -1,
            self._tts_channels,
        )
        normalized = pcm.astype(np.float32) / 32768.0
        resampled = self._tts_resampler.resample_chunk(normalized, last=False)
        return (np.clip(resampled, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()

    async def _finish_tts_input(self) -> None:
        if not self._is_playing or not self._is_receiving_tts:
            return
        self._is_receiving_tts = False
        if self._tts_remainder:
            logger.warning('Discarded an incomplete final Wyoming TTS sample')
        await self._end_tts_input()

    async def _abort_tts(self, *, text: str, code: str) -> None:
        """Reject bad TTS input while allowing already-queued audio to drain."""
        if not self._is_playing or not self._is_receiving_tts:
            return
        self._is_receiving_tts = False
        await self.send(Error(text=text, code=code).event())
        await self._end_tts_input()

    async def _end_tts_input(self) -> None:
        """Terminate the audio sequence and wait for its final playback signal."""
        if not self._has_tts_audio:
            await self._finish_playback()
            return
        store.dispatch(
            AudioPlayAudioSequenceAction(
                sample=None,
                id=self._sequence_id,
                index=self._sequence_index,
            ),
        )
        create_task(self._wait_for_playback())

    async def _wait_for_playback(self) -> None:
        try:
            await asyncio.wait_for(
                self._playback_done.wait(),
                timeout=PLAYBACK_DONE_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning('Wyoming TTS playback did not report completion')
        finally:
            await self._finish_playback()

    async def _finish_playback(self) -> None:
        if not self._is_playing:
            return
        self._is_playing = False
        self._tts_rate = None
        self._tts_channels = None
        self._tts_resampler = None
        self._tts_remainder = b''
        self._is_receiving_tts = False
        with contextlib.suppress(ConnectionError, OSError):
            await self.send(Played().event())
        if self._is_armed:
            store.dispatch(
                WyomingReportSatelliteStatusAction(
                    status=WyomingSatelliteStatus.CONNECTED,
                    client=self._peer,
                ),
            )


class SatelliteServer:
    """Own one listener and at most one active Wyoming satellite session."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        access: PeerAccess,
    ) -> None:
        """Initialize one TCP listener constrained by the selected peer policy."""
        self._server = AsyncTcpServer(host, port)
        self._access = access
        self._active: SatelliteEventHandler | None = None

    async def start(self) -> None:
        """Start accepting one authorized Home Assistant satellite client."""
        await self._server.start(self._create_handler)
        store.dispatch(
            WyomingReportSatelliteStatusAction(
                status=WyomingSatelliteStatus.LISTENING,
            ),
        )

    async def stop(self) -> None:
        """Close the listening socket and its active connection."""
        if self._active is not None:
            await self._active.stop()
            self._active = None
        await self._server.stop()
        store.dispatch(
            WyomingReportSatelliteStatusAction(
                status=WyomingSatelliteStatus.STOPPED,
            ),
        )

    async def activate(self, handler: SatelliteEventHandler) -> None:
        """Atomically replace an old satellite once the new peer speaks."""
        if self._active is handler:
            return
        if self._active is not None:
            await self._active.stop()
        self._active = handler
        store.dispatch(
            WyomingReportSatelliteStatusAction(
                status=WyomingSatelliteStatus.CONNECTED,
                client=handler._peer,  # noqa: SLF001
            ),
        )

    async def disconnect(self, handler: SatelliteEventHandler) -> None:
        """Reset status only when the active peer disconnects."""
        if self._active is handler:
            self._active = None
            store.dispatch(
                WyomingReportSatelliteStatusAction(
                    status=WyomingSatelliteStatus.LISTENING,
                ),
            )

    async def enqueue_microphone(self, sample: bytes) -> None:
        """Forward local microphone PCM only to the active authorized session."""
        if self._active is not None:
            await self._active.enqueue_microphone(sample)

    async def wake(self, phrase: str, detector: str) -> None:
        """Ask the active session to run one Home Assistant pipeline."""
        if self._active is None:
            logger.debug('A Home Assistant wake word fired with no satellite client')
            return
        await self._active.wake(phrase, detector)

    async def playback_done(self, event: AudioPlaybackDoneEvent) -> None:
        """Forward the audio manager's drain signal to the matching connection."""
        if self._active is not None:
            await self._active.notify_playback_done(event.id)

    def _create_handler(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> AsyncEventHandler:
        peer_name = writer.get_extra_info('peername')
        peer = peer_name[0] if isinstance(peer_name, tuple) and peer_name else ''
        if not self._access.allows(peer):
            logger.warning('Rejected unauthorized Wyoming satellite peer %s', peer)
            writer.close()
            return _RejectedSatelliteHandler(reader, writer)
        return SatelliteEventHandler(reader, writer, server=self, peer=peer)
