# pyright: reportMissingImports=false,reportMissingModuleSource=false
"""Module for managing audio playback and recording."""
from __future__ import annotations

import contextlib
import math
import time
import wave

from headless_kivy_pi import IS_RPI

from ubo_app.logging import logger

if not IS_RPI:
    import sys

    from ubo_app.utils.fake import Fake

    sys.modules['alsaaudio'] = Fake()
    sys.modules['pulsectl'] = Fake()
    sys.modules['pyaudio'] = Fake()

import alsaaudio
import pulsectl
import pyaudio

# TODO(@sassanh): It's a dynamic value, so we should probably get it from somewhere
RESPEAKER_INDEX = 1
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

    stream: pyaudio.PyAudio.Stream | None = None

    def __init__(self: AudioManager) -> None:
        """Initialize the audio manager."""
        # create an audio object
        self.pyaudio = pyaudio.PyAudio()
        self.is_playing = False
        self.should_stop = False

        self.cardindex = None
        try:
            cards = alsaaudio.cards()
            self.cardindex = cards.index(
                next(card for card in cards if 'wm8960' in card),
            )
            try:
                with pulsectl.Pulse('set-default-sink') as pulse:
                    for sink in pulse.sink_list():
                        if sink.proplist['alsa.card'] == self.cardindex:
                            pulse.sink_default_set(sink)
                            break
            except pulsectl.PulseError:
                logger.error('Not able to connect to pulseaudio')
        except StopIteration:
            logger.error('No audio card found')

    def __del__(self: AudioManager) -> None:
        """Clean up the audio manager."""
        self.close_stream()
        self.pyaudio.terminate()

    def close_stream(self: AudioManager) -> None:
        """Clean up the audio manager."""
        if self.stream:
            self.should_stop = True
            while self.is_playing:
                time.sleep(0.05)
            self.should_stop = False
            with contextlib.suppress(Exception):
                self.stream.close()
            self.stream = None

    def play(self: AudioManager, filename: str) -> None:
        """Play a waveform audio file.

        Parameters
        ----------
        filename : str
            Path to wav file
        """
        # open the file for reading.
        self.close_stream()

        logger.info('Opening audio file for playback', extra={'filename_': filename})
        try:
            with wave.open(filename, 'rb') as wf:
                self.is_playing = True
                stream = self.stream = self.pyaudio.open(
                    format=self.pyaudio.get_format_from_width(wf.getsampwidth()),
                    channels=wf.getnchannels(),
                    rate=wf.getframerate(),
                    output=True,
                    output_device_index=RESPEAKER_INDEX,
                )
                data = wf.readframes(CHUNK_SIZE)
                while data and not self.should_stop and stream.is_active():
                    stream.write(data)
                    data = wf.readframes(CHUNK_SIZE)
        except Exception as exception:  # noqa: BLE001
            logger.error(
                'Something went wrong while playing an audio file',
                exc_info=exception,
            )
        finally:
            self.is_playing = False
            self.close_stream()

    def set_playback_mute(self: AudioManager, *, mute: bool = False) -> None:
        """Set the playback mute of the audio output.

        Parameters
        ----------
        mute : bool
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
        volume : float
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
        volume : float
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
