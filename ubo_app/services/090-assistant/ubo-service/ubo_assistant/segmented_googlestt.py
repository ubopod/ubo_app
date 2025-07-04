"""Segmented Google STT Service for pipecat."""

from collections.abc import AsyncGenerator, Callable, Coroutine
from types import CoroutineType
from typing import Protocol

from pipecat.frames.frames import Frame, SystemFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessorSetup
from pipecat.services.google.stt import GoogleSTTService
from pipecat.services.stt_service import SegmentedSTTService


class _PushFrameSignature(Protocol):
    def __call__(
        self,
        frame: Frame,
        direction: FrameDirection = FrameDirection.DOWNSTREAM,
    ) -> CoroutineType: ...


class SegmentedGoogleSTTService(SegmentedSTTService):
    """Buffers speech while VAD says SPEAKING, then hands one chunk to Google."""

    def __init__(
        self,
        *,
        credentials: str | None = None,
        credentials_path: str | None = None,
        location: str = 'global',
        sample_rate: int | None = None,
        params: GoogleSTTService.InputParams | None = None,
        **kwargs: object,
    ) -> None:
        """Initialize the segmented Google STT service."""
        self._google = GoogleSTTService(
            credentials=credentials,
            credentials_path=credentials_path,
            location=location,
            sample_rate=sample_rate,
            params=params,
            **kwargs,
        )

        def push_frame_wrapper(
            original_push_frame: Callable[
                [Frame, FrameDirection],
                Coroutine[None, None, None],
            ],
        ) -> _PushFrameSignature:
            async def push_frame(
                frame: Frame,
                direction: FrameDirection = FrameDirection.DOWNSTREAM,
            ) -> None:
                await original_push_frame(frame, direction)
                if not isinstance(frame, SystemFrame):
                    await self.push_frame(frame, direction)

            return push_frame

        self._google.push_frame = push_frame_wrapper(self._google.push_frame)

        super().__init__(sample_rate=sample_rate, **kwargs)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process frame with the selected service."""
        if isinstance(frame, SystemFrame):
            await super().process_frame(frame, direction)
        await self._google.process_frame(frame, direction)

    async def setup(self, setup: FrameProcessorSetup) -> None:
        """Set up all sub-services."""
        await super().setup(setup)
        await self._google.setup(setup)

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Run the STT service on the provided audio data."""
        _ = audio
        yield None
