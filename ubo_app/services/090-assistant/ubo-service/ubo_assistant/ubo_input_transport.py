"""Ubo Input Transport for Pipecat Reading Audio Samples from UBO RPC Client."""

from pipecat.frames.frames import (
    InputAudioRawFrame,
    StartFrame,
)
from pipecat.transports.base_input import BaseInputTransport
from pipecat.transports.base_transport import TransportParams
from ubo_bindings.client import UboRPCClient
from ubo_bindings.ubo.v1 import (
    AudioReportSampleEvent,
    Event,
)


class UboInputTransport(BaseInputTransport):
    """Input transport that reads audio samples from UBO RPC Client."""

    def __init__(
        self,
        params: TransportParams,
        *,
        client: UboRPCClient,
        **kwargs: object,
    ) -> None:
        """Initialize the UboInputTransport with the given parameters and client."""
        self.client = client
        super().__init__(params, **kwargs)

    async def start(self, frame: StartFrame) -> None:
        """Start the transport and subscribe to audio sample events."""
        await super().start(frame)
        await self.set_transport_ready(frame)
        self.client.subscribe_event(
            Event(audio_report_sample_event=AudioReportSampleEvent()),
            self.queue_sample,
        )

    def queue_sample(self, event: Event) -> None:
        """Queue the audio sample from the event."""
        if event.audio_report_sample_event:
            audio = event.audio_report_sample_event.sample_speech_recognition
            self.task_manager.create_task(
                self.push_audio_frame(
                    InputAudioRawFrame(audio=audio, sample_rate=16000, num_channels=1),
                ),
                name='ubo_provider_audio_input',
            )
