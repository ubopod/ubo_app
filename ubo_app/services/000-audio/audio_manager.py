# pyright: reportMissingModuleSource=false
"""Module for managing audio playback and recording."""

from __future__ import annotations

import asyncio
import contextlib
import math
import wave
from asyncio import get_event_loop
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import TYPE_CHECKING, Any

import alsaaudio
import numpy as np
import simpleaudio
import soxr
from simpleaudio import _simpleaudio  # pyright: ignore [reportAttributeAccessIssue]
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_fixed,
)

from ubo_app.constants import SPEECH_RECOGNITION_FRAME_RATE
from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.audio import (
    AudioPlaybackDoneAction,
    AudioReportSampleAction,
    AudioSample,
    AudioSequenceSource,
)
from ubo_app.utils import IS_RPI
from ubo_app.utils.async_ import create_task
from ubo_app.utils.eeprom import get_eeprom_data
from ubo_app.utils.error_handlers import report_service_error
from ubo_app.utils.server import send_command

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

INPUT_FRAME_RATE = 48_000
INPUT_CHANNELS = 2
INPUT_PERIOD_SIZE = int(INPUT_FRAME_RATE / 1000) * 50  # 50ms


def _linear_to_logarithmic(volume_linear: float) -> int:
    """Convert a linear volume to a logarithmic volume.

    Assuming volume_linear is between 0 and 1
    Convert it to a logarithmic scale.
    """
    if volume_linear == 0:
        return 0
    return round(100 * math.log(volume_linear * 500) / math.log(500))


def _describe_capture_device_holder(card_index: int | None) -> str:
    """Best-effort: name the process holding the (exclusive) ALSA capture device.

    Reads the kernel's ``/proc/asound`` PCM substream status files for the
    ``owner_pid`` of whatever currently holds the capture device, then resolves
    that pid to its ``comm``/``cmdline``. This turns a "Device or resource busy
    [hw:0]" failure into a named culprit instead of a mystery. Never raises.
    """
    from pathlib import Path

    pattern = (
        f'card{card_index}/pcm*c/sub*/status'
        if card_index is not None
        else 'card*/pcm*c/sub*/status'
    )
    holders: list[str] = []
    for status_path in Path('/proc/asound').glob(pattern):
        with contextlib.suppress(OSError):
            text = status_path.read_text()
            owner_pid = next(
                (
                    line.split(':', 1)[1].strip()
                    for line in text.splitlines()
                    if line.startswith('owner_pid')
                ),
                None,
            )
            if not owner_pid:
                continue
            comm = cmdline = '?'
            with contextlib.suppress(OSError):
                comm = Path(f'/proc/{owner_pid}/comm').read_text().strip()
            with contextlib.suppress(OSError):
                cmdline = (
                    Path(f'/proc/{owner_pid}/cmdline')
                    .read_bytes()
                    .replace(b'\x00', b' ')
                    .decode('utf-8', 'replace')
                    .strip()
                )
            holders.append(
                f'{status_path}: pid={owner_pid} comm={comm} cmdline={cmdline}',
            )
    if not holders:
        return (
            'no ALSA owner_pid found (device may be held outside ALSA or already '
            'released)'
        )
    return ' | '.join(holders)


class AudioManager:
    """Class for managing audio playback and recording."""

    def __init__(self) -> None:
        """Initialize the audio manager."""
        import atexit

        # Ensure native audio threads are stopped on process exit,
        # even if close() is not called (e.g. SIGTERM, Ctrl+C).
        atexit.register(simpleaudio.stop_all)

        # create an audio object
        self.has_speakers = False
        self.has_microphones = False

        self.playback_mute = True
        self.playback_volume = 0.1
        self.capture_volume = 0.1

        self.audio_buffers: dict[str, dict[int, AudioSample | None]] = {}
        self.audio_heads: dict[str, int] = {}
        self.audio_buffers_lock = Lock()

        eeprom_data = get_eeprom_data()

        if (
            (speakers := eeprom_data.get('speakers'))
            and speakers.get('model') == 'wm8960'
        ):
            self.has_speakers = True

        if (
            (microphones := eeprom_data.get('microphones'))
            and microphones.get('model') == 'wm8960'
        ):
            self.has_microphones = True

        self._is_closed = False
        self._input_pcm: Any = None
        self._read_executor: ThreadPoolExecutor | None = None

        self.initialized = asyncio.Event()

        def signal_initialized(task: asyncio.Task) -> None:
            del task
            self.initialized.set()

        create_task(self.find_card_index(), callback=signal_initialized)
        create_task(self.stream_mic())

        if not IS_RPI:
            import pyaudio

            self.pa = pyaudio.PyAudio()
        else:
            self.pa = None

    def close(self) -> None:
        """Close the audio manager and release the audio devices."""
        # Signal the mic-streaming loop to stop and free the (exclusive) ALSA
        # capture device so the next AudioManager — e.g. after a service
        # restart — can open it instead of hitting "Device or resource busy".
        self._is_closed = True
        # Stop any in-progress playback so native threads don't outlive the process
        simpleaudio.stop_all()
        self._release_input()
        # Close the audio buffers
        with self.audio_buffers_lock:
            self.audio_buffers.clear()
            self.audio_heads.clear()

    def _release_input(self) -> None:
        """Close the capture PCM and its read executor, freeing the ALSA device."""
        if self._input_pcm is not None:
            with contextlib.suppress(Exception):
                self._input_pcm.close()
            self._input_pcm = None
        if self._read_executor is not None:
            self._read_executor.shutdown(wait=False)
            self._read_executor = None

    async def find_card_index(self) -> None:
        """Find the card index of the audio device."""
        self.card_index = None
        if not self.has_speakers and not self.has_microphones:
            return
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_fixed(1),
            retry=retry_if_exception(lambda e: isinstance(e, StopIteration)),
        ):
            with attempt:
                # Get the card index of the audio device
                cards = alsaaudio.cards()
                logger.debug(
                    'Audio - Available ALSA cards',
                    extra={'cards': cards},
                )
                self.card_index = cards.index(
                    next(card for card in cards if 'wm8960' in card),
                )
            if attempt.retry_state.outcome and isinstance(
                attempt.retry_state.outcome.exception(),
                StopIteration,
            ):
                report_service_error(exception=attempt.retry_state.outcome.exception())
                await send_command('audio', 'failure_report', has_output=True)
            else:
                break
        else:
            logger.error(
                'Audio - Failed to find the card index after multiple trials',
            )
            return
        logger.debug(
            'Audio - Selected card index',
            extra={
                'card_index': self.card_index,
                'card_name': alsaaudio.cards()[self.card_index],
            },
        )
        # In case they were set before the card was initialized
        self.set_playback_mute(mute=self.playback_mute)
        self.set_playback_volume(self.playback_volume)
        self.set_capture_volume(self.capture_volume)

    async def play_file(self, filename: str) -> None:
        """Play a waveform audio file.

        Parameters
        ----------
        filename: str
            Path to wav file

        """
        # open the file for reading.
        logger.info(
            'Audio - Opening audio file for playback',
            extra={'filename_': filename},
        )
        logger.debug(
            'Audio - Playback state',
            extra={
                'card_index': self.card_index,
                'has_speakers': self.has_speakers,
                'playback_mute': self.playback_mute,
                'playback_volume': self.playback_volume,
            },
        )
        with wave.open(filename, 'rb') as wave_file:
            sample_rate = wave_file.getframerate()
            channels = wave_file.getnchannels()
            sample_width = wave_file.getsampwidth()
            audio_data = wave_file.readframes(wave_file.getnframes())

            await self.play_sample(
                AudioSample(
                    data=audio_data,
                    channels=channels,
                    rate=sample_rate,
                    width=sample_width,
                ),
            )

    async def play_sample(
        self,
        sample: AudioSample,
    ) -> None:
        """Play an audio sample.

        Parameters
        ----------
        sample: AudioSample
            Audio sample as a sequence of bytes and its parameters: sample rate, width
            and channels

        """
        if sample.data == b'':
            return
        logger.verbose(
            'Audio - Playing sample',
            extra={
                'channels': sample.channels,
                'rate': sample.rate,
                'width': sample.width,
                'data_length': len(sample.data),
                'duration_seconds': len(sample.data)
                / (sample.rate * sample.channels * sample.width),
            },
        )
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_fixed(1),
        ):
            with attempt:
                play_object = simpleaudio.play_buffer(
                    audio_data=sample.data,
                    num_channels=sample.channels,
                    sample_rate=sample.rate,
                    bytes_per_sample=sample.width,
                )
                play_object.wait_done()
            if attempt.retry_state.outcome and attempt.retry_state.outcome.exception():
                if isinstance(
                    attempt.retry_state.outcome.exception(),
                    _simpleaudio.SimpleaudioError,
                ):
                    logger.info(
                        'Audio - Reporting the playback issue to ubo-system',
                        extra={'attempt': attempt.retry_state.attempt_number},
                    )
                    report_service_error(
                        exception=attempt.retry_state.outcome.exception(),
                    )
                    await send_command('audio', 'failure_report', has_output=True)
            else:
                logger.verbose(
                    'Audio - Sample playback completed successfully',
                    extra={'attempt': attempt.retry_state.attempt_number},
                )
                break
        else:
            logger.error(
                'Audio - Failed to play sample after multiple trials',
            )
            return

    async def play_sequence(  # noqa: C901, PLR0912, PLR0915
        self,
        sample: AudioSample | None,
        *,
        id: str,
        index: int,
        source: AudioSequenceSource = AudioSequenceSource.OTHER,
    ) -> None:
        """Play a sequence of audio samples.

        Parameters
        ----------
        sample: AudioSample
            Audio sample as a sequence of bytes and its parameters: sample rate, width
            and channels

        id: str
            ID of the audio sequence chain

        index: int
            Index of the sample in the sequence

        source: AudioSequenceSource
            Origin discriminator propagated to the matching
            ``AudioPlaybackDoneAction`` so cross-service consumers (e.g. the
            chat overlay) can match the same value they queued with.

        """
        logger.debug(
            'Audio - play_sequence called',
            extra={
                'sequence_id': id,
                'sample_index': index,
                'has_sample': sample is not None,
                'sample_data_length': len(sample.data) if sample else 0,
            },
        )
        with self.audio_buffers_lock:
            if not (already_playing := id in self.audio_buffers):
                self.audio_buffers[id] = {}
                # Start the head at the FIRST received index, not 0.
                # If AudioStopPlaybackAction cleared the buffer mid-stream
                # (e.g. on "okay enough"), the next chunk for the same id
                # arrives at a high index — Pipecat's UboOutputTransport
                # ratchets ``_audio_assistance_index`` across utterances.
                # Anchoring the head to ``index`` avoids the loop hanging on
                # ``await asyncio.sleep(0.05)`` forever waiting for an index 0
                # sample that will never arrive.
                self.audio_heads[id] = index

        buffer = self.audio_buffers[id]
        buffer[index] = sample

        if already_playing or sample is None:
            return

        class NotProvided: ...

        not_provided = NotProvided()

        logger.debug(
            'Audio - Starting sequence playback',
            extra={
                'sequence_id': id,
                'using_pyaudio': self.pa is not None,
                'card_index': self.card_index,
                'playback_mute': self.playback_mute,
                'playback_volume': self.playback_volume,
            },
        )

        if self.pa:
            default_info = self.pa.get_default_output_device_info()
            default_playback_index = default_info['index']
            if not isinstance(default_playback_index, int):
                msg = 'Default output device index is not an integer'
                raise RuntimeError(msg)

            stream = self.pa.open(
                format=self.pa.get_format_from_width(sample.width),
                channels=sample.channels,
                rate=sample.rate,
                output=True,
                frames_per_buffer=1024,
                output_device_index=default_playback_index,
            )

            async def play(sample: AudioSample) -> None:
                """Play a sample using PyAudio."""
                chunk_size = 1024 * sample.channels * sample.width
                for i in range(0, len(sample.data), chunk_size):
                    chunk = sample.data[i : i + chunk_size]
                    stream.write(chunk)
        else:
            stream = alsaaudio.PCM(
                type=alsaaudio.PCM_PLAYBACK,
                mode=alsaaudio.PCM_NORMAL,
                channels=sample.channels,
                rate=sample.rate,
                format=alsaaudio.PCM_FORMAT_S16_LE,
                periodsize=len(sample.data) // (sample.channels * sample.width),
            )

            async def play(sample: AudioSample) -> None:
                stream.write(sample.data)

        # Fallback grace period when a producer doesn't send the
        # ``sample=None`` end-of-stream sentinel. Every well-behaved
        # producer (``010-speech-synthesis``, the live pipecat pipeline
        # via ``UboOutputTransport``, the request pipeline via
        # ``GRPCTerminalCollector``) emits the sentinel and short-
        # circuits via the ``None`` arm below; this timeout is the
        # safety net for misbehaving producers. The warning logged when
        # it fires tells us a sentinel is missing somewhere.
        _empty_buffer_fallback_grace_seconds = 1.0
        _poll_interval_seconds = 0.05
        _max_empty_polls = int(
            _empty_buffer_fallback_grace_seconds / _poll_interval_seconds,
        )
        empty_polls = 0
        fallback_fired = False
        while id in self.audio_heads:
            head_sample = buffer.get(self.audio_heads.get(id, -1), not_provided)
            if head_sample is None:
                # None signals end-of-stream — the producer's sentinel.
                break
            if isinstance(head_sample, NotProvided):
                empty_polls += 1
                if empty_polls >= _max_empty_polls:
                    # Buffer empty past the fallback window — the producer
                    # never sent its end-of-stream sentinel. Surface so
                    # the missing sentinel can be tracked down; behaviour
                    # is still correct (we break out as before).
                    fallback_fired = True
                    break
                await asyncio.sleep(_poll_interval_seconds)
                continue
            empty_polls = 0
            head_index = self.audio_heads[id]
            await play(head_sample)
            buffer.pop(head_index, None)
            if id in self.audio_heads:
                self.audio_heads[id] += 1

        if fallback_fired:
            logger.warning(
                'Audio - Sequence ended via empty-buffer fallback; '
                'producer did not send an end-of-stream sentinel '
                '(``sample=None`` action). This is correct but adds '
                '~1 s of latency before the chat overlay can dismiss.',
                extra={'sequence_id': id, 'source': source.value},
            )
        logger.debug(
            'Audio - Sequence playback finished',
            extra={'sequence_id': id},
        )
        with self.audio_buffers_lock:
            self.audio_buffers.pop(id, None)
            self.audio_heads.pop(id, None)
            # Propagate the original sequence's ``source`` so consumers
            # (e.g. the chat reducer's "TTS playback finished" branch)
            # match the same discriminator they used for the queue action.
            store.dispatch(AudioPlaybackDoneAction(id=id, source=source))

        if self.pa:
            import pyaudio

            if isinstance(stream, pyaudio.Stream):
                stream.stop_stream()
        stream.close()

    async def _initialize_input_reader(  # noqa: C901
        self,
    ) -> Callable[[], Coroutine[None, None, tuple[int, bytes, int]]]:
        # Release any previously-opened capture handle before acquiring a new
        # one — the ALSA capture device is exclusive, so a leaked handle makes
        # the open below fail with "Device or resource busy".
        self._release_input()

        if self._is_closed:

            async def read_audio_chunk() -> tuple[int, bytes, int]:
                await asyncio.sleep(0.1)
                return 0, b'', 1

            return read_audio_chunk

        self._read_executor = read_executor = ThreadPoolExecutor(max_workers=1)

        if self.pa:
            import pyaudio

            try:
                channels = self.pa.get_default_input_device_info()['maxInputChannels']
                if not isinstance(channels, int) or channels < 1:

                    async def read_audio_chunk() -> tuple[int, bytes, int]:
                        await asyncio.sleep(0.1)
                        return 0, b'', 1
                else:
                    input_audio = self.pa.open(
                        format=pyaudio.paInt16,
                        channels=channels,
                        rate=INPUT_FRAME_RATE,
                        input=True,
                        frames_per_buffer=INPUT_PERIOD_SIZE,
                    )
                    self._input_pcm = input_audio

                    async def read_audio_chunk() -> tuple[int, bytes, int]:
                        data = await get_event_loop().run_in_executor(
                            read_executor,
                            input_audio.read,
                            INPUT_PERIOD_SIZE,
                            False,  # noqa: FBT003
                        )
                        return len(data), data, channels
            except OSError:
                logger.exception('Audio - Error opening audio capture')

                async def read_audio_chunk() -> tuple[int, bytes, int]:
                    await asyncio.sleep(0.1)
                    return 0, b'', 1
        else:
            import alsaaudio  # type: ignore [reportMissingModuleSource=false]

            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_fixed(1),
                reraise=True,
            ):
                with attempt:
                    if self.card_index is None:
                        msg = 'Card index is not set'
                        raise RuntimeError(msg)
                    input_audio = alsaaudio.PCM(
                        alsaaudio.PCM_CAPTURE,
                        alsaaudio.PCM_NORMAL,
                        channels=INPUT_CHANNELS,
                        rate=INPUT_FRAME_RATE,
                        format=alsaaudio.PCM_FORMAT_S16_LE,
                        periodsize=INPUT_PERIOD_SIZE,
                        cardindex=self.card_index,
                    )
                if attempt.retry_state.outcome and isinstance(
                    attempt.retry_state.outcome.exception(),
                    Exception,
                ):
                    if isinstance(
                        attempt.retry_state.outcome.exception(),
                        alsaaudio.ALSAAudioError,
                    ):
                        logger.info(
                            'Audio - Reporting the audio capture issue to ubo-system',
                            extra={'attempt': attempt.retry_state.attempt_number},
                        )
                        logger.warning(
                            'Audio - Capture device busy; identifying the holder',
                            extra={
                                'attempt': attempt.retry_state.attempt_number,
                                'holder': _describe_capture_device_holder(
                                    self.card_index,
                                ),
                            },
                        )
                        report_service_error(
                            exception=attempt.retry_state.outcome.exception(),
                        )
                        await send_command('audio', 'failure_report', has_output=True)
                    continue
                break
            else:
                # Since reraise is set to True, this part should be unreachable
                logger.error(
                    'Audio - Failed to open audio capture after multiple trials',
                )
                msg = 'Failed to open audio capture after multiple trials'
                raise RuntimeError(msg)

            self._input_pcm = input_audio

            async def read_audio_chunk() -> tuple[int, bytes, int]:
                result = await get_event_loop().run_in_executor(
                    read_executor,
                    input_audio.read,
                )
                return (*result, INPUT_CHANNELS)

        return read_audio_chunk

    async def stream_mic(self) -> None:
        """Stream audio from the microphone to the store."""
        read_audio_chunk = await self._initialize_input_reader()
        event_loop = get_event_loop()

        while not self._is_closed:
            try:
                length, data, channels = await read_audio_chunk()
            except alsaaudio.ALSAAudioError:
                if self._is_closed:
                    break
                logger.exception('Audio - Error reading audio capture')
                read_audio_chunk = await self._initialize_input_reader()
                continue
            else:
                if length > 0:
                    data_speech_recognition = np.frombuffer(data, dtype=np.int16)
                    data_speech_recognition = data_speech_recognition.reshape(
                        -1,
                        channels,
                    )
                    data_speech_recognition = data_speech_recognition.T
                    data_speech_recognition = (
                        data_speech_recognition.astype(np.float32) / 32768.0
                    )

                    data_speech_recognition = (
                        data_speech_recognition.squeeze()
                        if channels == 1
                        else np.mean(data_speech_recognition, axis=0)
                    )

                    if INPUT_FRAME_RATE != SPEECH_RECOGNITION_FRAME_RATE:
                        data_speech_recognition = soxr.resample(
                            data_speech_recognition,
                            in_rate=INPUT_FRAME_RATE,
                            out_rate=SPEECH_RECOGNITION_FRAME_RATE,
                        )

                    data_speech_recognition = (
                        (data_speech_recognition * 32768.0).astype(np.int16).tobytes()
                    )
                    store.dispatch(
                        AudioReportSampleAction(
                            timestamp=event_loop.time(),
                            sample_speech_recognition=data_speech_recognition,
                            sample=AudioSample(
                                data=data,
                                channels=channels,
                                rate=INPUT_FRAME_RATE,
                                width=2,
                            ),
                        ),
                    )

    def set_playback_mute(self, *, mute: bool = False) -> None:
        """Set the playback mute of the audio output.

        Parameters
        ----------
        mute: bool
            Mute to set

        """
        logger.debug(
            'Audio - Setting playback mute',
            extra={'mute': mute, 'card_index': self.card_index},
        )
        self.playback_mute = mute
        try:
            # Assume pulseaudio is installed
            mixer = alsaaudio.Mixer(control='Master')
            mixer.setmute(1 if mute else 0)
        except alsaaudio.ALSAAudioError:
            # Seems like pulseaudio is not installed, so we directly use device mixers
            if self.card_index is None or not self.has_speakers:
                return

            try:
                mixer = alsaaudio.Mixer(
                    control='Right Output Mixer PCM',
                    cardindex=self.card_index,
                )
                mixer.setmute(0)
                mixer = alsaaudio.Mixer(
                    control='Left Output Mixer PCM',
                    cardindex=self.card_index,
                )
                mixer.setmute(0)
            except alsaaudio.ALSAAudioError:
                create_task(self.find_card_index())

    def set_playback_volume(self, volume: float = 0.8) -> None:
        """Set the playback volume of the audio output.

        Parameters
        ----------
        volume: float
            Volume to set, a float between 0 and 1

        """
        if volume < 0 or volume > 1:
            msg = 'Volume must be between 0 and 1'
            raise ValueError(msg)
        logger.debug(
            'Audio - Setting playback volume',
            extra={
                'volume_linear': volume,
                'volume_log': _linear_to_logarithmic(volume),
                'card_index': self.card_index,
            },
        )
        self.playback_volume = volume
        try:
            # Assume pulseaudio is installed
            mixer = alsaaudio.Mixer(control='Master')
            mixer.setvolume(round(volume * 100))
        except alsaaudio.ALSAAudioError:
            # Seems like pulseaudio is not installed, so we directly use device mixers
            if self.card_index is None or not self.has_speakers:
                return

            try:
                mixer = alsaaudio.Mixer(control='Speaker', cardindex=self.card_index)
                mixer.setvolume(
                    _linear_to_logarithmic(volume),
                    alsaaudio.MIXER_CHANNEL_ALL,
                    alsaaudio.PCM_PLAYBACK,
                )
                mixer = alsaaudio.Mixer(control='Playback', cardindex=self.card_index)
                mixer.setvolume(
                    100,
                    alsaaudio.MIXER_CHANNEL_ALL,
                    alsaaudio.PCM_PLAYBACK,
                )
            except alsaaudio.ALSAAudioError:
                create_task(self.find_card_index())

    def set_capture_volume(self, volume: float = 0.8) -> None:
        """Set the capture volume of the audio output.

        Parameters
        ----------
        volume: float
            Volume to set, a float between 0 and 1

        """
        if volume < 0 or volume > 1:
            msg = 'Volume must be between 0 and 1'
            raise ValueError(msg)
        self.capture_volume = volume
        try:
            # Assume pulseaudio is installed
            mixer = alsaaudio.Mixer(control='Capture')
            mixer.setrec(round(volume * 100))
        except alsaaudio.ALSAAudioError:
            # Seems like pulseaudio is not installed, so we directly use device mixers
            if self.card_index is None or not self.has_microphones:
                return

            try:
                mixer = alsaaudio.Mixer(control='Capture', cardindex=self.card_index)
                mixer.setvolume(
                    _linear_to_logarithmic(volume),
                    alsaaudio.MIXER_CHANNEL_ALL,
                    alsaaudio.PCM_CAPTURE,
                )
            except alsaaudio.ALSAAudioError:
                create_task(self.find_card_index())
