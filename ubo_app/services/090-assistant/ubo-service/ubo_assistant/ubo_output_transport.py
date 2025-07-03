"""Ubo Output Transport for Pipecat Writing Audio Samples to UBO RPC Client."""

import uuid

from pipecat.frames.frames import (
    OutputAudioRawFrame,
    StartFrame,
)
from pipecat.transports.base_output import BaseOutputTransport
from pipecat.transports.base_transport import TransportParams
from ubo_bindings.client import UboRPCClient
from ubo_bindings.ubo.v1 import (
    AcceptableAssistanceFrame,
    Action,
    AssistanceAudioFrame,
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
        self._assistance_index = 0
        super().__init__(params, **kwargs)

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
        self._assistance_index += 1

    async def write_audio_frame(self, frame: OutputAudioRawFrame) -> None:
        """Write an audio frame to the UBO RPC Client."""
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
                    index=self._assistance_index,
                ),
            ),
        )
