"""Module for managing audio playback and recording."""
# pyright: reportMissingImports=false
from __future__ import annotations

import contextlib
import time
import wave
from typing import Mapping

import alsaaudio
import pyaudio

from ubo_app.logging import logger

RESPEAKER_INDEX = 1
CHUNK_SIZE = 1024


class AudioManager:
    """Class for managing audio playback and recording."""

    def __init__(self: AudioManager) -> None:
        """Initialize the audio manager."""
        # create an audio object
        self.pyaudio = pyaudio.PyAudio()
        try:
            cards = alsaaudio.cards()
            self.cardindex = cards.index(
                next(card for card in cards if 'wm8960' in card),
            )
        except StopIteration:
            logger.error('No audio card found')

    def __del__(self: AudioManager) -> None:
        """Clean up the audio manager."""
        self.pyaudio.terminate()

    def play(self: AudioManager, filename: str) -> None:
        """Play a waveform audio file.

        Parameters
        ----------
        filename : str
            Path to wav file
        """
        # open the file for reading.
        logger.info('Opening audio file for playback', extra={'filename_': filename})
        stream = None
        try:
            with wave.open(filename, 'rb') as wf:
                stream = self.pyaudio.open(
                    format=self.pyaudio.get_format_from_width(wf.getsampwidth()),
                    channels=wf.getnchannels(),
                    rate=wf.getframerate(),
                    output=True,
                    output_device_index=RESPEAKER_INDEX,
                )

                data = wf.readframes(CHUNK_SIZE)
                while data:
                    stream.write(data)
                    data = wf.readframes(CHUNK_SIZE)
                stream.close()
        except Exception as exception:  # noqa: BLE001
            logger.error(
                'Something went wrong while playing an audio file',
                exc_info=exception,
            )
        finally:
            # cleanup stuff.
            if stream:
                with contextlib.suppress(Exception):
                    stream.stop_stream()
                with contextlib.suppress(Exception):
                    stream.close()

    def set_playback_mute(self: AudioManager, *, mute: bool = False) -> None:
        """Set the playback mute of the audio output.

        Parameters
        ----------
        mute : bool
            Mute to set
        """
        mixer = alsaaudio.Mixer(
            control='Right Output Mixer PCM',
            cardindex=self.cardindex,
        )
        mixer.setmute(1 if mute else 0)
        mixer = alsaaudio.Mixer(
            control='Left Output Mixer PCM',
            cardindex=self.cardindex,
        )
        mixer.setmute(1 if mute else 0)

    def set_playback_volume(self: AudioManager, volume: float = 0.8) -> None:
        """Set the playback volume of the audio output.

        Parameters
        ----------
        volume : float
            Volume to set, a float between 0 and 1
        """
        if volume < 0 or volume > 1:
            msg = 'Volume must be between 0 and 1'
            raise ValueError(msg)
        mixer = alsaaudio.Mixer(control='Speaker', cardindex=self.cardindex)
        mixer.setvolume(
            round(100),
            alsaaudio.MIXER_CHANNEL_ALL,
            alsaaudio.PCM_PLAYBACK,
        )
        mixer = alsaaudio.Mixer(control='Playback', cardindex=self.cardindex)
        mixer.setvolume(
            round(volume * 100),
            alsaaudio.MIXER_CHANNEL_ALL,
            alsaaudio.PCM_PLAYBACK,
        )

    def set_capture_volume(self: AudioManager, volume: float = 0.8) -> None:
        """Set the capture volume of the audio output.

        Parameters
        ----------
        volume : float
            Volume to set, a float between 0 and 1
        """
        if volume < 0 or volume > 1:
            msg = 'Volume must be between 0 and 1'
            raise ValueError(msg)
        mixer = alsaaudio.Mixer(control='Capture', cardindex=self.cardindex)
        mixer.setrec(
            round(volume * 100),
            alsaaudio.MIXER_CHANNEL_ALL,
            alsaaudio.PCM_CAPTURE,
        )
