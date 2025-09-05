"""Implementation of switch service for the pipecat pipeline."""

import uuid
from typing import Generic, TypeVar

from betterproto.lib.google.protobuf import StringValue
from pipecat.frames.frames import Frame, StartFrame, StopFrame, SystemFrame
from pipecat.processors.frame_processor import (
    FrameDirection,
    FrameProcessor,
    FrameProcessorSetup,
)
from pipecat.services.ai_service import AIService
from ubo_bindings.client import UboRPCClient
from ubo_bindings.ubo.v1 import AcceptableAssistanceFrame, Action, AssistantReportAction

T = TypeVar('T', bound=FrameProcessor)


class UboSwitchService(AIService, Generic[T]):
    """Switch service for pipecat, altering between sub services.

    Allows switching between different pipecat services in the pipeline.
    """

    _services: dict[str, T | None]
    _assistance_id: str
    _assistance_index: int

    def __init__(self, client: UboRPCClient, *, selector: str) -> None:
        """Initialize the ubo switch service."""
        self._reset_assistance()
        self.client = client
        self._start_frame: StartFrame | None = None
        self._store_selector = selector

        for service in self.services.values():
            service.push_frame = self.push_frame
        self.selected_service: T | None = None

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
    def services(self) -> dict[str, T]:
        """List of initialized services."""
        return {
            id: service for id, service in self._services.items() if service is not None
        }

    def _start(self) -> None:
        @self.client.autorun([self._store_selector])
        def handle_stt_service_change(data: list[StringValue]) -> None:
            selected_stt = data[0].value
            self.create_task(self.set_selected_service(selected_stt))

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process frame with the selected service."""
        if isinstance(frame, StartFrame):
            self._start_frame = frame
            self._start()
        if self.selected_service:
            await self.selected_service.process_frame(frame, direction)
        elif isinstance(frame, SystemFrame):
            await super().process_frame(frame, direction)

    async def setup(self, setup: FrameProcessorSetup) -> None:
        """Set up all sub-services."""
        await super().setup(setup)
        for service in self.services.values():
            await service.setup(setup)

    async def set_selected_service(self, id: str) -> None:
        """Set the currently selected service."""
        if id not in self.services:
            msg = f'Service {id} is not available in the switch service `{type(self)}`.'
            raise ValueError(msg)
        if self.selected_service:
            await self.selected_service.queue_frame(StopFrame())
        newly_selected_service = self.services.get(id, None)
        if newly_selected_service and self._start_frame:
            await newly_selected_service.queue_frame(self._start_frame)
        self.selected_service = newly_selected_service
