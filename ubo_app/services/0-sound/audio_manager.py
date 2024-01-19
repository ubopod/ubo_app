"""Module for managing audio playback and recording."""
# pyright: reportMissingImports=false
from __future__ import annotations

import contextlib
import math
import time
import wave

import alsaaudio
import pulsectl
import pyaudio

from ubo_app.logging import logger

# TODO(@sassanh): It's a dynamic value, so we should probably get it from somewhere
RESPEAKER_INDEX = 1
CHUNK_SIZE = 1024


def set_default_sink(*, name: str) -> None:
    """Set the default sink to the sink with the given name."""
    with pulsectl.Pulse('set-default-sink-by-description') as pulse:
        for sink in pulse.sink_list():
            if sink.proplist['alsa.long_card_name'] == name:
                pulse.sink_default_set(sink)
                logger.info('Set default sink to', extra={'sink': sink})
                return
        logger.error('No sink found', extra={'name': name})


def linear_to_logarithmic(volume_linear: float) -> int:
    """Convert a linear volume to a logarithmic volume.

    Assuming volume_linear is between 0 and 1
    Convert it to a logarithmic scale.
    """
    if volume_linear == 0:
        return 0
    return round(100 * math.log(volume_linear) / math.log(100))


class AudioManager:
    """Class for managing audio playback and recording."""

    stream: pyaudio.PyAudio.Stream | None = None

    def __init__(self: AudioManager) -> None:
        """Initialize the audio manager."""
        # create an audio object
        self.pyaudio = pyaudio.PyAudio()
        self.is_playing = False
        self.should_stop = False

        cardindex = None
        try:
            cards = alsaaudio.cards()
            cardindex = cards.index(
                next(card for card in cards if 'wm8960' in card),
            )
        except StopIteration:
            logger.error('No audio card found')

        if cardindex is None:
            return

        mixer = alsaaudio.Mixer(
            control='Right Output Mixer PCM',
            cardindex=cardindex,
        )
        mixer.setmute(0)
        mixer = alsaaudio.Mixer(
            control='Left Output Mixer PCM',
            cardindex=cardindex,
        )
        mixer.setmute(0)

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
        mixer = alsaaudio.Mixer(control='Master')
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
        mixer = alsaaudio.Mixer(control='Master')
        mixer.setvolume(round(volume * 100))

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
        mixer = alsaaudio.Mixer(control='Capture')
        mixer.setrec(
            round(volume * 100), alsaaudio.MIXER_CHANNEL_ALL, alsaaudio.PCM_CAPTURE
        )
