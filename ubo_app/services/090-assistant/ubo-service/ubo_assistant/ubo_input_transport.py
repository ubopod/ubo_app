"""Ubo Input Transport for Pipecat Reading Audio Samples from UBO RPC Client."""

import threading
from enum import StrEnum

import numpy as np
from loguru import logger
from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    StartFrame,
    UserImageRawFrame,
    UserImageRequestFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.transports.base_input import BaseInputTransport
from pipecat.transports.base_transport import TransportParams
from ubo_bindings.client import UboRPCClient
from ubo_bindings.ubo.v1 import (
    Action,
    AudioReportSampleEvent,
    DisplayRedrawAction,
    DisplayRenderEvent,
    Event,
)


class VideoSource(StrEnum):
    """Enum for video sources."""

    CAMERA = 'camera'
    DISPLAY = 'display'


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
        self.audio_subscription = None
        self.audio_subscription_lock = threading.Lock()

        self._image: dict[VideoSource, np.ndarray] = {
            VideoSource.DISPLAY: np.zeros((0, 0, 3), dtype=np.uint8),
            VideoSource.CAMERA: np.zeros((0, 0, 3), dtype=np.uint8),
        }

        client.dispatch(
            action=Action(
                display_redraw_action=DisplayRedrawAction(),
            ),
        )

        client.subscribe_event(
            event_type=Event(display_render_event=DisplayRenderEvent()),
            callback=self._render_display,
        )
        super().__init__(params, **kwargs)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process incoming frames including user image requests."""
        await super().process_frame(frame, direction)

        if (
            isinstance(frame, UserImageRequestFrame)
            and frame.video_source in VideoSource.__members__.values()
        ):
            video_source = VideoSource(frame.video_source)
            (h, w, *_) = self._image[video_source].shape

            image_frame = UserImageRawFrame(
                user_id='-',
                request=frame,
                image=self._image[video_source].tobytes(),
                size=(w, h),
                format='RGB',
            )
            image_frame.transport_source = video_source
            await self.push_video_frame(image_frame)

    def _render_display(self, event: Event) -> None:
        """Render the display from a DisplayRenderEvent on an in-memory buffer."""
        if render_event := event.display_render_event:
            (y1, x1, y2, x2) = render_event.rectangle
            (canvas_width, canvas_height) = (
                int(240 * render_event.density),
                int(240 * render_event.density),
            )
            data = render_event.data
            required_height = max(
                self._image[VideoSource.DISPLAY].shape[0],
                canvas_width,
            )
            required_width = max(
                self._image[VideoSource.DISPLAY].shape[1],
                canvas_height,
            )
            required_shape = (required_height, required_width, 3)

            if (
                self._image[VideoSource.DISPLAY].shape[0] < required_height
                or self._image[VideoSource.DISPLAY].shape[1] < required_width
            ):
                new_display = np.zeros(required_shape, dtype=np.uint8)
                h, w = self._image[VideoSource.DISPLAY].shape[:2]
                new_display[:h, :w, :] = self._image[VideoSource.DISPLAY]
                self._image[VideoSource.DISPLAY] = new_display
            self._image[VideoSource.DISPLAY][y1:y2, x1:x2, :] = np.frombuffer(
                data,
                dtype=np.uint8,
            ).reshape((y2 - y1, x2 - x1, 4))[:, :, :3]

    def _set_is_listening(self, *, is_listening: bool) -> None:
        with self.audio_subscription_lock:
            if is_listening:
                if self.audio_subscription is None:
                    self.audio_subscription = self.client.subscribe_event(
                        Event(audio_report_sample_event=AudioReportSampleEvent()),
                        self.queue_sample,
                    )
                    logger.info(
                        'UboInputTransport is now listening for audio samples.',
                    )
            elif self.audio_subscription:
                self.audio_subscription()
                self.audio_subscription = None
                logger.info(
                    'UboInputTransport is no longer listening for audio samples.',
                )

    async def start(self, frame: StartFrame) -> None:
        """Start the transport and subscribe to audio sample events."""
        await super().start(frame)
        await self.set_transport_ready(frame)
        self.client.autorun(['state.assistant.is_listening'])(
            lambda results: self._set_is_listening(is_listening=results[0].value),
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
