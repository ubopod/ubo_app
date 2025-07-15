# pyright: reportMissingModuleSource=false
"""Module for managing audio playback and recording."""

from __future__ import annotations

import asyncio
import math
import wave
from asyncio import get_event_loop
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import TYPE_CHECKING

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
    AudioReportSampleEvent,
    AudioSample,
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
INPUT_PERIOD_SIZE = int(INPUT_FRAME_RATE / 1000) * 20  # 20ms


def _linear_to_logarithmic(volume_linear: float) -> int:
    """Convert a linear volume to a logarithmic volume.

    Assuming volume_linear is between 0 and 1
    Convert it to a logarithmic scale.
    """
    if volume_linear == 0:
        return 0
    return round(100 * math.log(volume_linear * 500) / math.log(500))


class AudioManager:
    """Class for managing audio playback and recording."""

    def __init__(self) -> None:
        """Initialize the audio manager."""
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

        if eeprom_data['speakers'] and eeprom_data['speakers']['model'] == 'wm8960':
            self.has_speakers = True

        if (
            eeprom_data['microphones']
            and eeprom_data['microphones']['model'] == 'wm8960'
        ):
            self.has_microphones = True

        create_task(self.find_card_index())
        create_task(self.stream_mic())

        if not IS_RPI:
            import pyaudio

            self.pa = pyaudio.PyAudio()
        else:
            self.pa = None

    def close(self) -> None:
        """Close the audio manager."""
        # Close the audio buffers
        with self.audio_buffers_lock:
            self.audio_buffers.clear()
            self.audio_heads.clear()

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
                break
        else:
            logger.error(
                'Audio - Failed to play sample after multiple trials',
            )
            return

    async def play_sequence(  # noqa: C901
        self,
        sample: AudioSample | None,
        *,
        id: str,
        index: int,
    ) -> None:
        """Play a sequence of audio.

        Parameters
        ----------
        sample: AudioSample
            Audio sample as a sequence of bytes and its parameters: sample rate, width
            and channels

        id: str
            ID of the audio sequence chain

        index: int
            Index of the sample in the sequence

        """
        with self.audio_buffers_lock:
            if not (already_playing := id in self.audio_buffers):
                self.audio_buffers[id] = {}
                self.audio_heads[id] = 0

        buffer = self.audio_buffers[id]
        buffer[index] = sample

        if already_playing or sample is None:
            return

        class NotProvided: ...

        not_provided = NotProvided()

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
                frames_per_buffer=len(sample.data),
                output_device_index=default_playback_index,
            )

            async def play(sample: AudioSample) -> None:
                """Play a sample using PyAudio."""
                stream.write(sample.data)
        else:
            stream = alsaaudio.PCM(
                type=alsaaudio.PCM_PLAYBACK,
                mode=alsaaudio.PCM_NORMAL,
                channels=sample.channels,
                rate=sample.rate,
                format=alsaaudio.PCM_FORMAT_S16_LE,
                periodsize=len(sample.data) // (2 * sample.width),
            )

            async def play(sample: AudioSample) -> None:
                stream.write(sample.data)

        while (
            id in self.audio_heads
            and (head_sample := buffer.get(self.audio_heads[id], not_provided))
            is not None
        ):
            if isinstance(head_sample, NotProvided):
                await asyncio.sleep(0.05)
                continue
            await play(head_sample)
            del buffer[self.audio_heads[id]]
            self.audio_heads[id] += 1

        with self.audio_buffers_lock:
            del self.audio_buffers[id]
            del self.audio_heads[id]
            store.dispatch(AudioPlaybackDoneAction(id=id))

        if self.pa:
            import pyaudio

            if isinstance(stream, pyaudio.Stream):
                stream.stop_stream()
        stream.close()

    async def _initialize_input_reader(  # noqa: C901
        self,
    ) -> Callable[[], Coroutine[None, None, tuple[int, bytes, int]]]:
        read_executor = ThreadPoolExecutor(max_workers=1)

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

        while True:
            try:
                length, data, channels = await read_audio_chunk()
            except alsaaudio.ALSAAudioError:
                logger.exception('Audio - Error reading audio capture')
                read_audio_chunk = await self._initialize_input_reader()
                break
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
                    store._dispatch(  # noqa: SLF001
                        [
                            AudioReportSampleEvent(
                                timestamp=event_loop.time(),
                                sample_speech_recognition=data_speech_recognition,
                                sample=AudioSample(
                                    data=data,
                                    channels=channels,
                                    rate=INPUT_FRAME_RATE,
                                    width=2,
                                ),
                            ),
                        ],
                    )

    def set_playback_mute(self, *, mute: bool = False) -> None:
        """Set the playback mute of the audio output.

        Parameters
        ----------
        mute: bool
            Mute to set

        """
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
