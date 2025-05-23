# pyright: reportMissingModuleSource=false
"""Module for managing audio playback and recording."""

from __future__ import annotations

import asyncio
import math
import wave
from asyncio import get_event_loop
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import alsaaudio
import simpleaudio
from simpleaudio import _simpleaudio  # pyright: ignore [reportAttributeAccessIssue]
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_fixed,
)

from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.audio import (
    AudioPlaybackDoneAction,
    AudioReportAudioEvent,
)
from ubo_app.utils import IS_RPI
from ubo_app.utils.async_ import create_task
from ubo_app.utils.eeprom import get_eeprom_data
from ubo_app.utils.error_handlers import report_service_error
from ubo_app.utils.server import send_command

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

INPUT_SAMPLE_RATE = 48_000
INPUT_CHANNELS = 2
INPUT_PERIOD_SIZE = 1 << 14


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

            await self.play_sequence(
                audio_data,
                channels=channels,
                rate=sample_rate,
                width=sample_width,
            )

    async def play_sequence(
        self,
        data: bytes,
        *,
        channels: int,
        rate: int,
        width: int,
        id: str | None = None,
    ) -> None:
        """Play a sequence of audio.

        Parameters
        ----------
        data: bytes
            Audio as a sequence of bytes

        channels: int
            Number of channels

        rate: int
            Frame rate of the audio

        width: int
            Sample width of the audio

        id: str | None
            ID of the audio sequence chain

        """
        if data != b'':
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_fixed(1),
            ):
                with attempt:
                    wave_object = simpleaudio.WaveObject(
                        audio_data=data,
                        num_channels=channels,
                        sample_rate=rate,
                        bytes_per_sample=width,
                    )
                    play_object = wave_object.play()
                    play_object.wait_done()
                if attempt.retry_state.outcome and isinstance(
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
                    'Audio - Failed to play audio file after multiple trials',
                )
                return
        if id is not None:
            store.dispatch(AudioPlaybackDoneAction(id=id))

    async def _initialize_input_reader(
        self,
    ) -> Callable[[], Coroutine[None, None, tuple[int, bytes]]]:
        read_executor = ThreadPoolExecutor(max_workers=1)

        if IS_RPI:
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
                        rate=INPUT_SAMPLE_RATE,
                        format=alsaaudio.PCM_FORMAT_S16_LE,
                        periodsize=INPUT_PERIOD_SIZE,
                        cardindex=self.card_index,
                    )
                if attempt.retry_state.outcome and isinstance(
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
                else:
                    break
            else:
                # Since reraise is set to True, this part should be unreachable
                logger.error(
                    'Audio - Failed to open audio capture after multiple trials',
                )
                msg = 'Failed to open audio capture after multiple trials'
                raise RuntimeError(msg)

            async def read_audio_chunk() -> tuple[int, bytes]:
                return await get_event_loop().run_in_executor(
                    read_executor,
                    input_audio.read,
                )

        else:
            try:
                import pyaudio

                pa = pyaudio.PyAudio()
                input_audio = pa.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=INPUT_SAMPLE_RATE,
                    input=True,
                    frames_per_buffer=INPUT_PERIOD_SIZE,
                )

                async def read_audio_chunk() -> tuple[int, bytes]:
                    data = await get_event_loop().run_in_executor(
                        read_executor,
                        input_audio.read,
                        INPUT_PERIOD_SIZE,
                        False,  # noqa: FBT003
                    )
                    return len(data), data
            except OSError:
                logger.exception('Audio - Error opening audio capture')

                async def read_audio_chunk() -> tuple[int, bytes]:
                    await asyncio.sleep(0.1)
                    return 0, b''

        return read_audio_chunk

    async def stream_mic(self) -> None:
        """Stream audio from the microphone to the store."""
        read_audio_chunk = await self._initialize_input_reader()
        event_loop = get_event_loop()
        while True:
            try:
                length, data = await read_audio_chunk()
            except alsaaudio.ALSAAudioError:
                logger.exception('Audio - Error reading audio capture')
                read_audio_chunk = await self._initialize_input_reader()
                break
            else:
                if length > 0:
                    store._dispatch(  # noqa: SLF001
                        [
                            AudioReportAudioEvent(
                                timestamp=event_loop.time(),
                                sample=data,
                                channels=INPUT_CHANNELS,
                                rate=INPUT_SAMPLE_RATE,
                                width=2,
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
