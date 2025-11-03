"""Implementation of switch service for the pipecat pipeline."""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Generic, TypeVar

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    LLMMessagesUpdateFrame,
    LLMSetToolsFrame,
    StartFrame,
    StopFrame,
    SystemFrame,
)
from pipecat.processors.aggregators.llm_context import NOT_GIVEN
from pipecat.processors.frame_processor import (
    FrameDirection,
    FrameProcessor,
    FrameProcessorSetup,
)
from pipecat.services.ai_service import AIService
from pipecat.services.llm_service import LLMService
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService
from ubo_bindings.ubo.v1 import (
    AcceptableAssistanceFrame,
    Action,
    AssistantReportAction,
)

from ubo_assistant.constants import DEFAULT_SYSTEM_MESSAGE, DEFAULT_TOOLS_MESSAGE
from ubo_assistant.tools import MCPServerMetadata

if TYPE_CHECKING:
    from betterproto.lib.google.protobuf import StringValue
    from pipecat.adapters.schemas.tools_schema import ToolsSchema
    from ubo_bindings.client import UboRPCClient

T = TypeVar('T', bound=FrameProcessor)

class UboSwitchService(AIService, Generic[T]):
    """Switch service for pipecat, altering between sub services.

    Allows switching between different pipecat services in the pipeline.
    """

    # Subclasses must define this before calling parent __init__
    _services: dict[str, T | None]

    def __init__(self, client: UboRPCClient, *, selector: str) -> None:
        """Initialize the ubo switch service."""
        self._reset_assistance()
        self.client = client
        self._store_selector = selector
        self._started = False
        self._mcp_servers_data = {}
        self._enabled_mcp_servers = set()

        for service in self.services.values():
            service.push_frame = self.push_frame
        self.selected_service: T | None = None
        self._current_service_id: str | None = None

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
        if self._started:
            return
        self._started = True

        # Autorun is called immediately with initial state value,
        # then again on changes. This handles all service types:
        # STT, LLM, TTS, and Image Generator
        @self.client.autorun([self._store_selector])
        def handle_service_change(data: list[StringValue]) -> None:
            selected_service_id = data[0].value
            logger.info('Service selection changed via autorun {extra}',
                extra={
                    'service_id': selected_service_id,
                    'selector': self._store_selector,
                },
            )
            self.create_task(self.set_selected_service(selected_service_id))

        # Only LLM services need to react to MCP server state changes
        if isinstance(self, LLMService):
            logger.info('Service is LLMService, subscribing to MCP state changes')

            @self.client.autorun([
                'state.assistant.enabled_mcp_servers_with_metadata_json',
            ])
            def handle_mcp_servers_change(data: list) -> None:
                """Handle MCP servers state changes from Redux store."""
                try:
                    import json

                    # Parse JSON string (wrapped in StringValue protobuf object)
                    # StringValue.value -> str
                    enabled_with_metadata_json = data[0].value

                    # Deserialize JSON to Python objects
                    # (list of enabled servers with metadata)
                    enabled_with_metadata = json.loads(enabled_with_metadata_json)

                    # Convert list to dict for internal use (O(1) lookups)
                    mcp_servers_dict = {}
                    enabled_servers_set = set()
                    for server_dict in enabled_with_metadata:
                        server_id = server_dict['server_id']
                        mcp_servers_dict[server_id] = MCPServerMetadata(
                            server_id=server_id,
                            name=server_dict['name'],
                            type=server_dict['type'],
                            config=server_dict['config'],
                        )
                        enabled_servers_set.add(server_id)

                    logger.info(
                        'MCP servers state changed via autorun',
                        extra={
                            'servers_count': len(mcp_servers_dict),
                            'enabled_count': len(enabled_servers_set),
                            'server_ids': list(mcp_servers_dict.keys()),
                        },
                    )

                    # Update internal state
                    self._mcp_servers_data = mcp_servers_dict
                    self._enabled_mcp_servers = enabled_servers_set

                    # Schedule async tool update with current service ID
                    if self._current_service_id:
                        self.create_task(
                            self._update_llm_tools(
                                service_id=self._current_service_id,
                                ),
                        )

                except Exception:
                    logger.exception('Error handling MCP servers state change')
                    self._mcp_servers_data = {}
                    self._enabled_mcp_servers = set()

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process frame with the selected service."""
        if isinstance(frame, StartFrame):
            logger.info(
                'UboSwitchService received StartFrame',
                extra={'class_name': self.__class__.__name__},
            )
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

    def _get_mcp_servers_from_state(self) -> list:
        """Get enabled MCP servers from stored state.

        Returns:
            List of enabled MCP server metadata

        """
        # Filter to only enabled servers from stored data
        enabled_servers = [
            server
            for server_id, server in self._mcp_servers_data.items()
            if server_id in self._enabled_mcp_servers
        ]
        logger.debug(
            'Filtered enabled MCP servers',
            extra={
                'enabled_ids': list(self._enabled_mcp_servers),
                'count': len(enabled_servers),
            },
        )
        return enabled_servers

    async def _get_combined_tools(
        self,
        llm_service: LLMService,
        *,
        mcp_enabled: bool = True,
    ) -> ToolsSchema:
        """Get combined tools with optional MCP tools.

        Args:
            llm_service: LLM service to register tools with
            mcp_enabled: Whether to include MCP tools (default: True)

        Returns:
            Combined tools schema

        """
        from ubo_assistant.tools import create_combined_tools

        logger.info('Starting to get combined tools')

        # Get enabled MCP servers if MCP is enabled
        mcp_servers = self._get_mcp_servers_from_state() if mcp_enabled else None

        logger.info(
            'Getting combined tools {extra}',
            extra={
                'mcp_enabled': mcp_enabled,
                'mcp_servers': mcp_servers,
            },
        )

        combined_tools = await create_combined_tools(
            llm_service=llm_service,
            mcp_servers=mcp_servers,
        )
        logger.info(
            'Combined tools ready',
            extra={'tool_count': len(combined_tools.standard_tools)},
        )
        return combined_tools

    def _check_tools_support(self, service_id: str | None) -> bool:
        """Check if the given service supports tools.

        Args:
            service_id: Service identifier ('ollama', 'ollama_onprem', etc.)

        Returns:
            True if tools are supported, False otherwise

        """
        # Cerebras does not supports tools (known limitation with JSON schema)
        # Ollama and Ollama OnPrem do not support tools
        if service_id in ['cerebras', 'ollama', 'ollama_onprem']:
            logger.info('{extra} does not support tools',
                        extra={'service_id': service_id},
                        )
            return False
        # All other services (OpenAI, Google Vertex, Grok) support tools by default
        return True

    async def _update_llm_tools(
        self,
        *,
        service_id: str,
    ) -> None:
        """Update LLM tools and optionally messages.

        Args:
            service_id: Service ID to check tool support for

        """
        if self.selected_service is None:
            return
        if not isinstance(self.selected_service, LLMService):
            return

        tools_supported = self._check_tools_support(service_id)

        if tools_supported:
            logger.info('Registering tools for: {extra}',
                extra={'service': self.selected_service},
            )
            combined_tools = await self._get_combined_tools(
                self.selected_service,
                mcp_enabled=True,
            )
            system_message = DEFAULT_SYSTEM_MESSAGE + DEFAULT_TOOLS_MESSAGE
            tool_count = len(combined_tools.standard_tools)
        else:
            logger.info('Not registering tools for: {extra}',
                extra={'service': self.selected_service},
            )
            combined_tools = NOT_GIVEN
            system_message = DEFAULT_SYSTEM_MESSAGE
            tool_count = 0

        await self.selected_service.queue_frame(
            LLMMessagesUpdateFrame(
                messages=[{'role': 'system', 'content': system_message}],
            ),
        )

        await self.selected_service.queue_frame(
            LLMSetToolsFrame(tools=combined_tools),
        )
        logger.info(
            'Updated LLM tools',
            extra={
                'tools_supported': tools_supported,
                'tool_count': tool_count,
            },
        )

    async def set_selected_service(self, id: str) -> None:
        """Set the currently selected service."""
        if id not in self.services:
            msg = f'Service {id} is not available in the switch service `{type(self)}`.'
            raise ValueError(msg)
        if self.selected_service:
            try:
                await self.selected_service.queue_frame(StopFrame())
            except Exception as e:  # noqa: BLE001
                logger.warning('Error stopping service {extra}',
                extra={
                    'stopped_service': self.selected_service,
                    'error': e,
                },
                )
        newly_selected_service = self.services.get(id, None)
        logger.info('Stopped: {extra}',
            extra={
                'stopped_service': self.selected_service,
            },
        )
        if newly_selected_service and self._start_frame:
            # Set selected_service so _update_llm_tools can queue frames
            self.selected_service = newly_selected_service

            try:
                await newly_selected_service.queue_frame(self._start_frame)
                if isinstance(newly_selected_service, LLMService):
                    # Update tools and messages for LLM service
                    await self._update_llm_tools(service_id=id)

                # Add a small delay for STT and TTS services
                # to establish WebSocket connections.
                # This prevents the NoneType has no attribute 'send'
                # error with AssemblyAI.
                # This also prevents silent audio frames with services like Rime TTS.
                if isinstance(newly_selected_service, (STTService, TTSService)):
                    logger.info('Waiting for STT service {id} \
                        to establish connection...', id=id)
                    await asyncio.sleep(0.2)  # 800ms delay for connection establishment

                logger.info('Started: {extra}',
                    extra={
                        'started_service': newly_selected_service,
                    },
                )
            except Exception as e:
                logger.exception('Error starting service {extra}',
                    extra={
                        'started_service': newly_selected_service,
                        'error': e,
                    },
                )
                # Don't set the service if starting failed
                self.selected_service = None
                self._current_service_id = None
                return
        else:
            self.selected_service = newly_selected_service

        # Track the service ID for MCP updates
        self._current_service_id = id
        logger.info('Selected: {extra}',
            extra={
                'selected_service': self.selected_service,
                    },
                )
