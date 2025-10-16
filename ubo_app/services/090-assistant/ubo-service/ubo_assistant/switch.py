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
from pipecat.processors.frame_processor import (
    FrameDirection,
    FrameProcessor,
    FrameProcessorSetup,
)
from pipecat.services.ai_service import AIService
from pipecat.services.cerebras.llm import CerebrasLLMService
from pipecat.services.llm_service import LLMService
from pipecat.services.ollama.llm import OLLamaLLMService
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService
from ubo_bindings.ubo.v1 import (
    AcceptableAssistanceFrame,
    Action,
    AssistantReportAction,
)

from ubo_assistant.constants import DEFAULT_SYSTEM_MESSAGE, DEFAULT_TOOLS_MESSAGE

if TYPE_CHECKING:
    from betterproto.lib.google.protobuf import StringValue
    from pipecat.adapters.schemas.tools_schema import ToolsSchema
    from ubo_bindings.client import UboRPCClient

T = TypeVar('T', bound=FrameProcessor)

class UboSwitchService(AIService, Generic[T]):
    """Switch service for pipecat, altering between sub services.

    Allows switching between different pipecat services in the pipeline.
    """

    _services: dict[str, T | None]
    _assistance_id: str
    _start_frame: StartFrame | None
    _started: bool
    _mcp_servers_data: dict
    _enabled_mcp_servers: set[str]

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

        @self.client.autorun([self._store_selector])
        def handle_stt_service_change(data: list[StringValue]) -> None:
            selected_stt = data[0].value
            self.create_task(self.set_selected_service(selected_stt))

        # Load MCP servers directly from filesystem
        self._load_mcp_servers_from_filesystem()

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

    def _load_mcp_servers_from_filesystem(self) -> None:
        """Load MCP servers directly from filesystem."""
        import json
        import os
        from pathlib import Path

        import platformdirs

        try:
            # Get the MCP servers path - use platformdirs to match main app
            config_path_env = os.environ.get('CONFIG_PATH')
            if config_path_env:
                config_path = Path(config_path_env)
            else:
                config_path = platformdirs.user_config_path(
                    appname='ubo',
                    ensure_exists=True,
                )
            mcp_servers_path = config_path / 'assistant_mcp_servers'

            logger.info(
                'Loading MCP servers from filesystem {extra}',
                extra={
                    'config_path': str(config_path),
                    'mcp_servers_path': str(mcp_servers_path),
                    'exists': mcp_servers_path.exists(),
                },
            )

            if not mcp_servers_path.exists():
                logger.info('MCP servers directory does not exist')
                self._mcp_servers_data = {}
                self._enabled_mcp_servers = set()
                return

            # Load all server configs
            for server_dir in mcp_servers_path.iterdir():
                if not server_dir.is_dir():
                    continue

                config_file = server_dir / 'config.json'
                if not config_file.exists():
                    continue

                try:
                    with config_file.open() as f:
                        data = json.load(f)

                    server_id = server_dir.name
                    # Extract name from server_id (format: name_uuid)
                    name_parts = server_id.rsplit('_', 1)
                    name = name_parts[0] if len(name_parts) == 2 else server_id  # noqa: PLR2004

                    # Create MCPServerMetadata instance
                    from ubo_assistant.tools import MCPServerMetadata

                    self._mcp_servers_data[server_id] = MCPServerMetadata(
                        server_id=server_id,
                        name=name,
                        type=data['type'],
                        config=data['config'],
                    )

                    # Check if enabled from JSON config
                    if data.get('enabled', False):
                        self._enabled_mcp_servers.add(server_id)

                except Exception:
                    logger.exception(
                        'Failed to load MCP server',
                        extra={'config_file': str(config_file)},
                    )
                    continue

            logger.info(
                'MCP servers loaded from filesystem {extra}',
                extra={
                    'servers_count': len(self._mcp_servers_data),
                    'enabled_count': len(self._enabled_mcp_servers),
                    'server_ids': list(self._mcp_servers_data.keys()),
                },
            )
        except Exception:
            logger.exception('Error loading MCP servers from filesystem')
            self._mcp_servers_data = {}
            self._enabled_mcp_servers = set()

    def _get_mcp_servers_from_state(self) -> list:
        """Get enabled MCP servers from stored state.

        Returns:
            List of enabled MCP server metadata

        """
        # Filter to only enabled servers from stored data
        return [
            server
            for server_id, server in self._mcp_servers_data.items()
            if server_id in self._enabled_mcp_servers
        ]

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

        return await create_combined_tools(
            llm_service=llm_service,
            mcp_servers=mcp_servers,
        )

    async def _update_llm_tools(self) -> None:
        """Update LLM tools when MCP servers change."""
        if not isinstance(self.selected_service, LLMService):
            return

        combined_tools = await self._get_combined_tools(
            self.selected_service,
            mcp_enabled=True,
        )
        await self.selected_service.queue_frame(
            LLMSetToolsFrame(tools=combined_tools),
        )
        logger.info(
            'Updated LLM tools',
            extra={'tool_count': len(combined_tools.standard_tools)},
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
            try:
                await newly_selected_service.queue_frame(self._start_frame)
                if isinstance(newly_selected_service, LLMService):
                    if isinstance(newly_selected_service,
                                    (OLLamaLLMService,
                                    CerebrasLLMService,
                                    ),
                                ):
                        new_messages = [
                            {'role': 'system', 'content': DEFAULT_SYSTEM_MESSAGE },
                        ]
                        combined_tools = []
                        logger.info('Not registering tools for: {extra}',
                            extra={
                                'service': newly_selected_service,
                            },
                        )
                    else:
                        logger.info('Registering tools for: {extra}',
                            extra={
                                'service': newly_selected_service,
                            },
                        )
                        new_messages = [
                            {'role': 'system',
                            'content': DEFAULT_SYSTEM_MESSAGE + DEFAULT_TOOLS_MESSAGE },
                        ]
                        # Load tools (standard + MCP if enabled)
                        combined_tools = await self._get_combined_tools(
                            newly_selected_service,
                            mcp_enabled=True,
                        )
                    await newly_selected_service.queue_frame(
                        LLMMessagesUpdateFrame(messages=new_messages),
                    )
                    await newly_selected_service.queue_frame(
                        LLMSetToolsFrame(tools=combined_tools),
                    )

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
                return
        self.selected_service = newly_selected_service
        logger.info('Selected: {extra}',
            extra={
                'selected_service': self.selected_service,
                    },
                )
