"""Implementation of switch service for the pipecat pipeline."""

import uuid
from collections.abc import Callable, Coroutine
from types import CoroutineType
from typing import Generic, Protocol, TypeVar

from pipecat.frames.frames import Frame, SystemFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessorSetup
from pipecat.services.ai_service import AIService
from ubo_bindings.client import UboRPCClient
from ubo_bindings.ubo.v1 import AcceptableAssistanceFrame, Action, AssistantReportAction

T = TypeVar('T', bound=AIService)


class _PushFrameSignature(Protocol):
    def __call__(
        self,
        frame: Frame,
        direction: FrameDirection = FrameDirection.DOWNSTREAM,
    ) -> CoroutineType: ...


class UboSwitchService(AIService, Generic[T]):
    """Switch service for pipecat, altering between sub services.

    Allows switching between different pipecat services in the pipeline.
    """

    _services: list[T | None]
    _assistance_id: str
    _assistance_index: int

    def __init__(self, client: UboRPCClient, **kwargs: object) -> None:
        """Initialize the ubo switch service."""
        self._reset_assistance()
        self.client = client

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

        for service in self.services:
            service.push_frame = push_frame_wrapper(service.push_frame)
        self.selected_service: T | None = next(iter(self.services), None)
        super().__init__(**kwargs)

    def _reset_assistance(self) -> None:
        self._assistance_id = uuid.uuid4().hex
        self._assistance_index = 0

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

    @property
    def services(self) -> list[T]:
        """List of initialized services."""
        return [service for service in self._services if service is not None]

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process frame with the selected service."""
        if isinstance(frame, SystemFrame):
            await super().process_frame(frame, direction)
        if not self.selected_service:
            return
        await self.selected_service.process_frame(frame, direction)

    async def setup(self, setup: FrameProcessorSetup) -> None:
        """Set up all sub-services."""
        await super().setup(setup)
        for service in self.services:
            await service.setup(setup)
