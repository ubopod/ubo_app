# pyright: reportMissingModuleSource=false
"""Module for managing audio playback and recording."""

from __future__ import annotations

import asyncio
import math
import subprocess

import alsaaudio
import simpleaudio

from ubo_app.logging import logger
from ubo_app.store.main import dispatch
from ubo_app.store.services.audio import AudioPlaybackDoneEvent
from ubo_app.utils import IS_RPI
from ubo_app.utils.async_ import create_task

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
        self.cardindex = None

        async def initialize_audio() -> None:
            while True:
                try:
                    cards = alsaaudio.cards()
                    self.cardindex = cards.index(
                        next(card for card in cards if 'wm8960' in card),
                    )
                except StopIteration:
                    logger.exception('No audio card found')
                except OSError:
                    logger.exception('Error while setting default sink')
                    logger.info('Restarting pulseaudio')

                    await self.restart_pulse_audio()

                    await asyncio.sleep(5)
                else:
                    break

        create_task(initialize_audio())

    async def restart_pulse_audio(self: AudioManager) -> None:
        """Restart pulseaudio."""
        if not IS_RPI:
            return
        process = await asyncio.create_subprocess_exec(
            '/usr/bin/env',
            'pulseaudio',
            '--kill',
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        await process.wait()
        process = await asyncio.create_subprocess_exec(
            '/usr/bin/env',
            'pulseaudio',
            '--start',
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        await process.wait()

    def play_file(self: AudioManager, filename: str) -> None:
        """Play a waveform audio file.

        Parameters
        ----------
        filename: str
            Path to wav file

        """
        # open the file for reading.
        logger.info('Opening audio file for playback', extra={'filename_': filename})
        simpleaudio.WaveObject.from_wave_file(filename).play()

    def play_sequence(
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
            simpleaudio.WaveObject(
                audio_data=data,
                num_channels=channels,
                sample_rate=rate,
                bytes_per_sample=width,
            ).play().wait_done()
        if id is not None:
            dispatch(AudioPlaybackDoneEvent(id=id))

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
            if self.cardindex is None:
                return

            mixer = alsaaudio.Mixer(
                control='Right Output Mixer PCM',
                cardindex=self.cardindex,
            )
            mixer.setmute(0)
            mixer = alsaaudio.Mixer(
                control='Left Output Mixer PCM',
                cardindex=self.cardindex,
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
            if self.cardindex is None:
                return

            mixer = alsaaudio.Mixer(control='Speaker', cardindex=self.cardindex)
            mixer.setvolume(
                _linear_to_logarithmic(volume),
                alsaaudio.MIXER_CHANNEL_ALL,
                alsaaudio.PCM_PLAYBACK,
            )
            mixer = alsaaudio.Mixer(control='Playback', cardindex=self.cardindex)
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
            if self.cardindex is None:
                return

            mixer = alsaaudio.Mixer(control='Capture', cardindex=self.cardindex)
            mixer.setvolume(
                _linear_to_logarithmic(volume),
                alsaaudio.MIXER_CHANNEL_ALL,
                alsaaudio.PCM_CAPTURE,
            )
