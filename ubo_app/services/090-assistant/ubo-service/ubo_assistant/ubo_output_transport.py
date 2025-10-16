"""Ubo Output Transport for Pipecat Writing Audio Samples to UBO RPC Client."""

import uuid

from loguru import logger
from pipecat.audio.resamplers.base_audio_resampler import BaseAudioResampler
from pipecat.audio.utils import create_stream_resampler
from pipecat.frames.frames import (
    Frame,
    OutputAudioRawFrame,
    OutputImageRawFrame,
    StartFrame,
)
from pipecat.transports.base_output import BaseOutputTransport
from pipecat.transports.base_transport import TransportParams
from ubo_bindings.client import UboRPCClient
from ubo_bindings.ubo.v1 import (
    AcceptableAssistanceFrame,
    Action,
    AssistanceAudioFrame,
    AssistanceImageFrame,
    AssistantReportAction,
    AudioSample,
)


class UboOutputTransport(BaseOutputTransport):
    """Output transport that writes audio samples to UBO RPC Client."""

    def __init__(
        self,
        params: TransportParams,
        *,
        client: UboRPCClient,
        **kwargs: object,
    ) -> None:
        """Initialize the UboOutputTransport with the given parameters and client."""
        self.client = client
        self._assistance_id = uuid.uuid4().hex
        self._audio_assistance_index = self._video_assistance_index = 0
        # Dictionary to store resamplers for different input sample rates
        self._resamplers: dict[int, BaseAudioResampler] = {}
        super().__init__(params, **kwargs)

    def _get_resampler_for_rate(self, input_rate: int) -> BaseAudioResampler:
        """Get or create a resampler for the given input sample rate."""
        if input_rate not in self._resamplers:
            self._resamplers[input_rate] = create_stream_resampler()
        return self._resamplers[input_rate]

    async def _handle_frame(self, frame: Frame) -> None:
        """Override frame handling to manage audio resampling properly."""
        if isinstance(frame, OutputAudioRawFrame):
            # Handle audio frames directly to avoid resampler conflicts
            target_sample_rate = 48000  # UBO target sample rate

            if frame.sample_rate != target_sample_rate:
                # Resample using our custom resampler management
                resampler = self._get_resampler_for_rate(frame.sample_rate)
                resampled_audio = await resampler.resample(
                    frame.audio,
                    frame.sample_rate,
                    target_sample_rate,
                )
                # Create new frame with resampled audio
                resampled_frame = OutputAudioRawFrame(
                    audio=resampled_audio,
                    sample_rate=target_sample_rate,
                    num_channels=frame.num_channels,
                )
                # Write directly to avoid BaseOutputTransport's resampler
                await self.write_audio_frame(resampled_frame)
            else:
                # No resampling needed
                await self.write_audio_frame(frame)
        else:
            # For non-audio frames, use the parent implementation
            await super()._handle_frame(frame)

    async def start(self, frame: StartFrame) -> None:
        """Start the transport and set it as ready."""
        await super().start(frame)
        await self.set_transport_ready(frame)

    def _report_assistance_frame(self, frame_data: AcceptableAssistanceFrame) -> None:
        self.client.dispatch(
            action=Action(
                assistant_report_action=AssistantReportAction(
                    source_id='pipecat',
                    data=frame_data,
                ),
            ),
        )

    async def write_audio_frame(self, frame: OutputAudioRawFrame) -> bool:
        """Write an audio frame to the UBO RPC Client.

        Returns:
            True if the audio frame was written successfully, False otherwise.

        """
        try:
            self._report_assistance_frame(
                AcceptableAssistanceFrame(
                    assistance_audio_frame=AssistanceAudioFrame(
                        audio=AudioSample(
                            data=frame.audio,
                            channels=frame.num_channels,
                            rate=frame.sample_rate,
                            width=2,
                        ),
                        timestamp=self.client.event_loop.time(),
                        id=self._assistance_id,
                        index=self._audio_assistance_index,
                    ),
                ),
            )
            self._audio_assistance_index += 1
        except Exception as exception:
            logger.exception(
                'Error writing audio frame {extra}',
                extra={'frame': frame, 'exception': exception},
            )
            return False
        else:
            return True

    async def write_video_frame(self, frame: OutputImageRawFrame) -> bool:
        """Write a video frame to the UBO RPC Client.

        Returns:
            True if the video frame was written successfully, False otherwise.

        """
        try:
            if frame.format in ('PNG', 'JPEG', 'RGB', None):
                self._report_assistance_frame(
                    AcceptableAssistanceFrame(
                        assistance_image_frame=AssistanceImageFrame(
                            image=frame.image,
                            width=frame.size[0],
                            height=frame.size[1],
                            format='RGB',
                            metadata=frame.metadata,
                            timestamp=self.client.event_loop.time(),
                            id=self._assistance_id,
                            index=self._video_assistance_index,
                        ),
                    ),
                )
                self._video_assistance_index += 1
                return True
        except Exception as exception:
            logger.exception(
                'Error writing video frame {extra}',
                extra={'frame': frame, 'exception': exception},
            )
            return False
        else:
            return False
