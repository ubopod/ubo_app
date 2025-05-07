# pyright: reportMissingModuleSource=false
"""Module for managing audio playback and recording."""

from __future__ import annotations

import math
import wave

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
from ubo_app.store.services.audio import AudioPlaybackDoneAction
from ubo_app.utils.async_ import create_task
from ubo_app.utils.eeprom import get_eeprom_data
from ubo_app.utils.error_handlers import report_service_error
from ubo_app.utils.server import send_command

CHUNK_SIZE = 1024


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

    def __init__(self: AudioManager) -> None:
        """Initialize the audio manager."""
        # create an audio object
        self.has_speakers = False
        self.has_microphones = False

        self.playback_mute = True
        self.playback_volume = 0.1
        self.capture_volume = 0.1

        eeprom_data = get_eeprom_data()

        if eeprom_data is not None and (
            'speakers' in eeprom_data
            and eeprom_data['speakers']
            and eeprom_data['speakers']['model'] == 'wm8960'
        ):
            self.has_speakers = True

        if eeprom_data is not None and (
            'microphones' in eeprom_data
            and eeprom_data['microphones']
            and eeprom_data['microphones']['model'] == 'wm8960'
        ):
            self.has_microphones = True

        create_task(self.find_card_index())

    async def find_card_index(self: AudioManager) -> None:
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
                'Failed to find the card index after multiple trials',
            )
            return
        cards = alsaaudio.cards()
        self.card_index = cards.index(
            next(card for card in cards if 'wm8960' in card),
        )
        # In case they were set before the card was initialized
        self.set_playback_mute(mute=self.playback_mute)
        self.set_playback_volume(self.playback_volume)
        self.set_capture_volume(self.capture_volume)

    async def play_file(self: AudioManager, filename: str) -> None:
        """Play a waveform audio file.

        Parameters
        ----------
        filename: str
            Path to wav file

        """
        # open the file for reading.
        logger.info('Opening audio file for playback', extra={'filename_': filename})
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
        self: AudioManager,
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
                        'Reporting the playback issue to ubo-system',
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
                    'Failed to play audio file after multiple trials',
                )
                return
        if id is not None:
            store.dispatch(AudioPlaybackDoneAction(id=id))

    def set_playback_mute(self: AudioManager, *, mute: bool = False) -> None:
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

    def set_playback_volume(self: AudioManager, volume: float = 0.8) -> None:
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

    def set_capture_volume(self: AudioManager, volume: float = 0.8) -> None:
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
