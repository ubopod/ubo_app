"""Ubo Input Transport for Pipecat Reading Audio Samples from UBO RPC Client."""

import threading

from loguru import logger
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
        self.subscription = None
        self.subscription_lock = threading.Lock()
        super().__init__(params, **kwargs)

    def _set_is_listening(self, *, is_listening: bool) -> None:
        with self.subscription_lock:
            if is_listening:
                if self.subscription is None:
                    self.subscription = self.client.subscribe_event(
                        Event(audio_report_sample_event=AudioReportSampleEvent()),
                        self.queue_sample,
                    )
                    logger.info(
                        'UboInputTransport is now listening for audio samples.',
                    )
            elif self.subscription:
                self.subscription()
                self.subscription = None
                logger.info(
                    'UboInputTransport is no longer listening for audio samples.',
                )

    async def start(self, frame: StartFrame) -> None:
        """Start the transport and subscribe to audio sample events."""
        await super().start(frame)
        await self.set_transport_ready(frame)
        self.client.autorun(['state.assistant.is_listening'])(
            lambda results: self._set_is_listening(is_listening=results[0]),
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
