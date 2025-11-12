"""Ubo Input Transport for Pipecat Reading Audio Samples from UBO RPC Client."""

import asyncio
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Callable
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
    AvailableInputDescription,
    CameraReportImageEvent,
    DisplayRedrawAction,
    DisplayRenderEvent,
    Event,
    InputDemandAction,
    QrCodeInputDescription,
)


class VideoSource(StrEnum):
    """Enum for video sources."""

    CAMERA = 'camera'
    DISPLAY = 'display'


@dataclass
class ReportedImage:
    """Image frame structure for storing image data with a timestamp."""

    timestamp: float
    data: np.ndarray


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
        self._is_listening = False
        self._zero_frame_task: asyncio.Task[None] | None = None
        self._audio_subscription: Callable[[], None] | None = None

        self._image_set_events: dict[VideoSource, asyncio.Event] = {
            key: asyncio.Event() for key in VideoSource
        }
        self._image: dict[VideoSource, ReportedImage] = {
            VideoSource.DISPLAY: ReportedImage(
                timestamp=0.0,
                data=np.zeros((0, 0, 3), dtype=np.uint8),
            ),
            VideoSource.CAMERA: ReportedImage(
                timestamp=0.0,
                data=np.zeros((0, 0, 3), dtype=np.uint8),
            ),
        }

        client.dispatch(
            action=Action(
                display_redraw_action=DisplayRedrawAction(),
            ),
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

            if video_source == VideoSource.CAMERA:
                timestamp = time.time()
                self.client.dispatch(
                    action=Action(
                        input_demand_action=InputDemandAction(
                            description=AvailableInputDescription(
                                qr_code_input_description=QrCodeInputDescription(
                                    pattern=None,
                                    title='Assistant Vision',
                                    prompt=f'For prompt: {frame.text}',
                                ),
                            ),
                        ),
                    ),
                )

                event = self._image_set_events[video_source]
                while self._image[video_source].timestamp < timestamp - 1:
                    await event.wait()
                    event.clear()

            last_reported_image = self._image[video_source]
            (h, w, *_) = last_reported_image.data.shape

            image_frame = UserImageRawFrame(
                user_id='-',
                text=frame.text,
                append_to_context=frame.append_to_context,
                image=last_reported_image.data.tobytes(),
                size=(w, h),
                format='RGB',
            )
            image_frame.transport_source = video_source
            await self.push_video_frame(image_frame)

    def _queue_audio_sample(self, event: Event) -> None:
        """Queue the audio sample from the event."""
        if event.audio_report_sample_event:
            audio = event.audio_report_sample_event.sample_speech_recognition
            self.task_manager.create_task(
                self.push_audio_frame(
                    InputAudioRawFrame(
                        audio=audio,
                        sample_rate=16000,
                        num_channels=1,
                    ),
                ),
                name='ubo_provider_audio_input',
            )

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
                self._image[VideoSource.DISPLAY].data.shape[0],
                canvas_width,
            )
            required_width = max(
                self._image[VideoSource.DISPLAY].data.shape[1],
                canvas_height,
            )
            required_shape = (required_height, required_width, 3)

            if (
                self._image[VideoSource.DISPLAY].data.shape[0] < required_height
                or self._image[VideoSource.DISPLAY].data.shape[1] < required_width
            ):
                new_display = np.zeros(required_shape, dtype=np.uint8)
                h, w = self._image[VideoSource.DISPLAY].data.shape[:2]
                new_display[:h, :w, :] = self._image[VideoSource.DISPLAY].data
                self._image[VideoSource.DISPLAY].data = new_display
            self._image[VideoSource.DISPLAY].data[y1:y2, x1:x2, :] = np.frombuffer(
                data,
                dtype=np.uint8,
            ).reshape((y2 - y1, x2 - x1, 4))[:, :, :3]
            self._image_set_events[VideoSource.DISPLAY].set()

    def _store_camera_image(self, event: Event) -> None:
        """Store the image coming from the camera."""
        if image_event := event.camera_report_image_event:
            self._image[VideoSource.CAMERA] = ReportedImage(
                data=np.frombuffer(
                    image_event.data,
                    dtype=np.uint8,
                ).reshape((image_event.height, image_event.width, 3)),
                timestamp=time.time(),
            )
            self._image_set_events[VideoSource.CAMERA].set()

    async def _send_zero_frames(self) -> None:
        """Send zero audio frames.

        This is used to keep streaming STT services alive when not listening.
        """
        try:
            # Send zero frames at 50ms intervals (16kHz * 0.05s = 800 samples)
            frame_duration = 0.05  # 50ms
            samples_per_frame = int(16000 * frame_duration)
            zero_audio = b'\x00' * (samples_per_frame * 2)  # 2 bytes per sample (int16)

            while not self._is_listening:
                await self.push_audio_frame(
                    InputAudioRawFrame(
                        audio=zero_audio,
                        sample_rate=16000,
                        num_channels=1,
                    ),
                )
                await asyncio.sleep(frame_duration)
        except asyncio.CancelledError:
            # Task was cancelled when switching to listening mode
            pass

    def _on_listening_state_changed(self, *, is_listening: bool) -> None:
        """Handle changes to the listening state."""
        self._is_listening = is_listening

        if is_listening:
            logger.info('UboInputTransport is now listening for audio samples.')
            # Subscribe to audio events when listening
            if self._audio_subscription is None:
                self._audio_subscription = self.client.subscribe_event(
                    event_type=Event(audio_report_sample_event=AudioReportSampleEvent()),
                    callback=self._queue_audio_sample,
                )
            # Stop sending zero frames when actively listening
            if self._zero_frame_task and not self._zero_frame_task.done():
                self._zero_frame_task.cancel()
                self._zero_frame_task = None
        else:
            logger.info('UboInputTransport is no longer listening for audio samples.')
            # Unsubscribe from audio events when not listening
            if self._audio_subscription is not None:
                self._audio_subscription()
                self._audio_subscription = None
            # Start sending zero frames when not listening
            if not self._zero_frame_task or self._zero_frame_task.done():
                self._zero_frame_task = self.task_manager.create_task(
                    self._send_zero_frames(),
                    name='ubo_zero_frame_sender',
                )

    async def start(self, frame: StartFrame) -> None:
        """Start the transport and subscribe to audio sample events."""
        await super().start(frame)
        await self.set_transport_ready(frame)

        # Subscribe to display and camera events (always active)
        self.client.subscribe_event(
            event_type=Event(display_render_event=DisplayRenderEvent()),
            callback=self._render_display,
        )
        self.client.subscribe_event(
            event_type=Event(camera_report_image_event=CameraReportImageEvent()),
            callback=self._store_camera_image,
        )

        # Monitor assistant listening state to conditionally subscribe to audio events
        self.client.autorun(['state.assistant.is_listening'])(
            lambda results: self._on_listening_state_changed(
                is_listening=results[0].value,
            ),
        )
