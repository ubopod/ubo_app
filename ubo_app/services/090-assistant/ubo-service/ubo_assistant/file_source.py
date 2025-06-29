"""Pipewire audio transport for testing the pipeline from a pcm file."""

import asyncio
from pathlib import Path

from pipecat.frames.frames import EndFrame, InputAudioRawFrame, StartFrame
from pipecat.transports.base_output import BaseOutputTransport
from pipecat.transports.base_transport import TransportParams


class FileAudio(BaseOutputTransport):
    """Pipewire audio transport for testing the pipeline from a pcm file."""

    def __init__(
        self,
        *,
        path: Path,
        params: TransportParams,
        **kwargs: object,
    ) -> None:
        """Initialize FileAudio transport."""
        self.path = path
        super().__init__(params, **kwargs)

    async def start(self, frame: StartFrame) -> None:
        """Start FileAudio transport."""
        await super().start(frame)

        self._audio_task = self.create_task(self.run())

    async def run(self) -> None:
        """Read the file and push its chunks as a sequence of frames."""
        with self.path.open('rb') as file:
            while True:
                chunk = file.read(320)
                if not chunk:
                    break
                frame = InputAudioRawFrame(
                    audio=chunk,
                    sample_rate=16000,
                    num_channels=1,
                )

                await self.push_frame(frame)
                await asyncio.sleep(0.02)

        # Signal end of audio
        await self.push_frame(EndFrame())


"""
Sample Usage:

ubo_provider = FileAudio(
    path=Path('./audio_file.raw'),
    params=TransportParams(
        audio_in_enabled=True,
        audio_in_channels=1,
        audio_in_sample_rate=16000,
    ),
)
"""
