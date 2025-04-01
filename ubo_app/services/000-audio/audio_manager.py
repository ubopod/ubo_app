# pyright: reportMissingModuleSource=false
"""Module for managing audio playback and recording."""

from __future__ import annotations

import asyncio
import math
import wave

import alsaaudio
import simpleaudio
from simpleaudio import _simpleaudio  # pyright: ignore [reportAttributeAccessIssue]

from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.audio import AudioPlaybackDoneAction
from ubo_app.utils.async_ import create_task
from ubo_app.utils.eeprom import get_eeprom_data
from ubo_app.utils.error_handlers import report_service_error
from ubo_app.utils.server import send_command

CHUNK_SIZE = 1024
TRIALS = 3


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
        self.card_index = None
        self.has_speakers = False
        self.has_microphones = False

        async def initialize_audio() -> None:
            for _ in range(TRIALS):
                try:
                    cards = alsaaudio.cards()
                    self.card_index = cards.index(
                        next(card for card in cards if 'wm8960' in card),
                    )
                except StopIteration:
                    logger.exception('No audio card found')
                    await send_command('audio', 'failure_report', has_output=True)
                else:
                    break
                await asyncio.sleep(1)

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

        if self.has_speakers or self.has_microphones:
            create_task(initialize_audio())

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
            for trial in range(TRIALS):
                try:
                    wave_object = simpleaudio.WaveObject(
                        audio_data=data,
                        num_channels=channels,
                        sample_rate=rate,
                        bytes_per_sample=width,
                    )
                    play_object = wave_object.play()
                    play_object.wait_done()
                except _simpleaudio.SimpleaudioError:
                    logger.info(
                        'Reporting the playback issue to ubo-system',
                        extra={'trial': trial},
                    )
                    report_service_error()
                    await send_command('audio', 'failure_report', has_output=True)
                else:
                    break
            else:
                logger.error(
                    'Failed to play audio file after multiple trials',
                    extra={'tried_times': TRIALS},
                )
        if id is not None:
            store.dispatch(AudioPlaybackDoneAction(id=id))

    def set_playback_mute(self: AudioManager, *, mute: bool = False) -> None:
        """Set the playback mute of the audio output.

        Parameters
        ----------
        mute: bool
            Mute to set

        """
        try:
            # Assume pulseaudio is installed
            mixer = alsaaudio.Mixer(control='Master')
            mixer.setmute(1 if mute else 0)
        except alsaaudio.ALSAAudioError:
            # Seems like pulseaudio is not installed, so we directly use device mixers
            if self.card_index is None or not self.has_speakers:
                return

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
        try:
            # Assume pulseaudio is installed
            mixer = alsaaudio.Mixer(control='Master')
            mixer.setvolume(round(volume * 100))
        except alsaaudio.ALSAAudioError:
            # Seems like pulseaudio is not installed, so we directly use device mixers
            if self.card_index is None or not self.has_speakers:
                return

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
        try:
            # Assume pulseaudio is installed
            mixer = alsaaudio.Mixer(control='Capture')
            mixer.setrec(round(volume * 100))
        except alsaaudio.ALSAAudioError:
            # Seems like pulseaudio is not installed, so we directly use device mixers
            if self.card_index is None or not self.has_microphones:
                return

            mixer = alsaaudio.Mixer(control='Capture', cardindex=self.card_index)
            mixer.setvolume(
                _linear_to_logarithmic(volume),
                alsaaudio.MIXER_CHANNEL_ALL,
                alsaaudio.PCM_CAPTURE,
            )
