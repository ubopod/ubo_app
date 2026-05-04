"""Ubo adapters for Pipecat's native service switchers."""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Generic, TypeVar, cast

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    LLMMessagesUpdateFrame,
    LLMSetToolsFrame,
    ManuallySwitchServiceFrame,
    StartFrame,
    SystemFrame,
)
from pipecat.pipeline.llm_switcher import LLMSwitcher
from pipecat.pipeline.service_switcher import ServiceSwitcher
from pipecat.processors.aggregators.llm_context import NOT_GIVEN
from pipecat.processors.frame_processor import (
    FrameDirection,
    FrameProcessor,
    FrameProcessorSetup,
)
from pipecat.services.llm_service import LLMService
from pipecat.services.settings import LLMSettings, ServiceSettings
from ubo_bindings.ubo.v1 import (
    AcceptableAssistanceFrame,
    Action,
    AssistantReportAction,
)

from ubo_assistant.constants import DEFAULT_SYSTEM_MESSAGE, DEFAULT_TOOLS_MESSAGE
from ubo_assistant.tools import MCPServerMetadata

if TYPE_CHECKING:
    from betterproto.lib.google.protobuf import StringValue
    from pipecat.services.mcp_service import MCPClient
    from ubo_bindings.client import UboRPCClient

    from ubo_assistant.tools import CombinedTools

T = TypeVar('T', bound=FrameProcessor)


class UboNoopService(FrameProcessor):
    """Inactive switch target that preserves lifecycle frames and swallows data."""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process lifecycle frames without invoking a provider."""
        await super().process_frame(frame, direction)
        if isinstance(frame, SystemFrame):
            await self.push_frame(frame, direction)


def make_empty_llm_settings() -> LLMSettings:
    """Build an LLMSettings with every field set to None (store-mode placeholder).

    Pipecat 1.0's ``ServiceSettings.validate_complete()`` rejects the default
    ``NOT_GIVEN`` sentinel, so wrappers that don't own any provider state still
    have to construct a fully-populated settings object. ``None`` means
    "unsupported" in store mode.
    """
    return LLMSettings(
        model=None,
        system_instruction=None,
        temperature=None,
        max_tokens=None,
        top_p=None,
        top_k=None,
        frequency_penalty=None,
        presence_penalty=None,
        seed=None,
        filter_incomplete_user_turns=None,
        user_turn_completion_config=None,
    )


class UboNoopLLMService(LLMService):
    """LLM-shaped no-op target for LLMSwitcher."""

    def __init__(self) -> None:
        """Initialize the no-op LLM."""
        super().__init__(settings=make_empty_llm_settings())

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process lifecycle frames without invoking an LLM."""
        await super().process_frame(frame, direction)
        if isinstance(frame, SystemFrame):
            await self.push_frame(frame, direction)


class UboSwitchMixin(Generic[T]):
    """Store-driven behavior shared by native Pipecat switcher adapters."""

    _services: dict[str, T | None]
    _ubo_services: dict[str, T | None]
    _noop_service: T

    def _initialize_ubo_switch(self, client: UboRPCClient, *, selector: str) -> None:
        self._reset_assistance()
        self.client = client
        self._store_selector = selector
        self._autoruns_started = False
        self._mcp_servers_data: dict[str, MCPServerMetadata] = {}
        self._enabled_mcp_servers: set[str] = set()
        self._mcp_clients: list[MCPClient] = []
        self._mcp_tools_update_lock = asyncio.Lock()
        self._processor_setup: FrameProcessorSetup | None = None
        self._current_service_id: str | None = None
        self.selected_service: T | None = None

        # Pipecat switcher events are async by default. Ubo's selected-service
        # bookkeeping is local and quick, so keep it in the switching path.
        native_switcher = cast('ServiceSwitcher', self)
        native_switcher.strategy._event_handlers[  # noqa: SLF001
            'on_service_switched'
        ].is_sync = True

        @native_switcher.strategy.event_handler('on_service_switched')
        def on_service_switched(
            _strategy: object,
            service: FrameProcessor,
        ) -> None:
            self._handle_service_switched(service)

    @property
    def service_map(self) -> dict[str, T]:
        """Initialized Ubo services keyed by store service id."""
        return {
            id: service
            for id, service in self._ubo_services.items()
            if service is not None
        }

    @property
    def switcher_services(self) -> list[T]:
        """Services passed to the native Pipecat switcher."""
        return [self._noop_service, *self.service_map.values()]

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

    def _service_id_for(self, service: FrameProcessor) -> str | None:
        for service_id, candidate in self.service_map.items():
            if candidate is service:
                return service_id
        return None

    def _handle_service_switched(self, service: FrameProcessor) -> None:
        service_id = self._service_id_for(service)
        self.selected_service = cast('T', service) if service_id is not None else None
        self._current_service_id = service_id

        logger.info(
            'Selected: {extra}',
            extra={
                'service_id': service_id,
                'selected_service': self.selected_service,
                'model': getattr(
                    getattr(self.selected_service, '_settings', None),
                    'model',
                    None,
                ),
            },
        )

        if (
            service_id is not None
            and isinstance(service, LLMService)
            and self._processor_setup is not None
        ):
            cast('ServiceSwitcher', self).create_task(
                self._update_llm_tools(service_id=service_id, llm_service=service),
            )

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Start Ubo autoruns, then delegate routing to Pipecat."""
        if isinstance(frame, StartFrame):
            logger.info(
                'Ubo native switcher received StartFrame',
                extra={'class_name': self.__class__.__name__},
            )
            self._start_frame = frame
            self._ensure_autoruns_started()
        await super().process_frame(frame, direction)  # pyright: ignore[reportAttributeAccessIssue]

    async def setup(self, setup: FrameProcessorSetup) -> None:
        """Store setup for dynamic services, then set up Pipecat branches."""
        await super().setup(setup)  # pyright: ignore[reportAttributeAccessIssue]
        self._processor_setup = setup

    async def cleanup(self) -> None:
        """Clean up switcher resources."""
        await self._close_mcp_clients(self._mcp_clients)
        self._mcp_clients = []
        await super().cleanup()  # pyright: ignore[reportAttributeAccessIssue]

    def _ensure_autoruns_started(self) -> None:
        if self._autoruns_started:
            return
        self._autoruns_started = True

        @self.client.autorun([self._store_selector])
        def handle_service_change(data: list[StringValue]) -> None:
            selected_service_id = data[0].value
            logger.info(
                'Service selection changed via autorun {extra}',
                extra={
                    'service_id': selected_service_id,
                    'selector': self._store_selector,
                },
            )
            cast('ServiceSwitcher', self).create_task(
                self.set_selected_service(selected_service_id),
            )

        if isinstance(self, UboLLMSwitchService):
            logger.info('Service is LLMSwitcher, subscribing to MCP state changes')
            self._setup_mcp_autorun()

    def _setup_mcp_autorun(self) -> None:
        """Set up autorun subscription for MCP server state changes."""

        @self.client.autorun([
            'state.assistant.enabled_mcp_servers_with_metadata',
        ])
        def handle_mcp_servers_change(data: list) -> None:
            """Handle MCP servers state changes from Redux store."""
            self._process_mcp_servers_data(data)

    def _process_mcp_servers_data(self, data: list) -> None:
        """Process MCP servers data from autorun callback."""
        try:
            enabled_with_metadata_wrapper = data[0]
            items_wrapper = getattr(
                enabled_with_metadata_wrapper,
                'items',
                None,
            )
            if items_wrapper is None:
                enabled_with_metadata = []
            else:
                enabled_with_metadata = getattr(items_wrapper, 'items', [])
            if not isinstance(enabled_with_metadata, list):
                enabled_with_metadata = []

            mcp_servers_dict = {}
            enabled_servers_set = set()
            for server_metadata in enabled_with_metadata:
                server_id = server_metadata.server_id
                config_wrapper = server_metadata.config
                stdio_cfg = getattr(config_wrapper, 'stdio_mcp_config', None)
                sse_cfg = getattr(config_wrapper, 'sse_mcp_config', None)
                if stdio_cfg:
                    config = stdio_cfg
                elif sse_cfg:
                    config = sse_cfg
                else:
                    config = config_wrapper
                mcp_servers_dict[server_id] = MCPServerMetadata(
                    server_id=server_id,
                    name=server_metadata.name,
                    type=server_metadata.type.name.lower(),
                    config=config,
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

            self._mcp_servers_data = mcp_servers_dict
            self._enabled_mcp_servers = enabled_servers_set

            if (
                self._current_service_id is not None
                and isinstance(
                    cast('ServiceSwitcher', self).strategy.active_service,
                    LLMService,
                )
            ):
                native_switcher = cast('ServiceSwitcher', self)
                active_service = cast(
                    'LLMService',
                    native_switcher.strategy.active_service,
                )
                native_switcher.create_task(
                    self._update_llm_tools(
                        service_id=self._current_service_id,
                        llm_service=active_service,
                    ),
                )

        except Exception:
            logger.exception('Error handling MCP servers state change')
            self._mcp_servers_data = {}
            self._enabled_mcp_servers = set()

    async def _close_mcp_clients(self, clients: list[MCPClient]) -> None:
        """Close MCP clients that are no longer backing registered tools."""
        for client in clients:
            try:
                await client.close()
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    'Error closing MCP client {extra}',
                    extra={
                        'client': client,
                        'error': e,
                    },
                )

    def _get_mcp_servers_from_state(self) -> list:
        """Get enabled MCP servers from stored state."""
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
    ) -> CombinedTools:
        """Get combined tools with optional MCP tools."""
        from ubo_assistant.tools import create_combined_tools

        logger.info('Starting to get combined tools')
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
            extra={'tool_count': len(combined_tools.tools_schema.standard_tools)},
        )
        return combined_tools

    def _check_tools_support(self, service_id: str | None) -> bool:
        """Check if the given service supports tools."""
        if service_id in ['cerebras', 'ollama', 'ollama_onprem']:
            logger.info(
                '{extra} does not support tools',
                extra={'service_id': service_id},
            )
            return False
        return True

    async def _update_llm_tools(
        self,
        *,
        service_id: str,
        llm_service: LLMService,
    ) -> None:
        """Update LLM tools and optionally messages."""
        async with self._mcp_tools_update_lock:
            tools_supported = self._check_tools_support(service_id)
            old_mcp_clients = self._mcp_clients
            new_mcp_clients: list[MCPClient] = []

            try:
                if tools_supported:
                    logger.info(
                        'Registering tools for: {extra}',
                        extra={'service': llm_service},
                    )
                    combined_tools = await self._get_combined_tools(
                        llm_service,
                        mcp_enabled=True,
                    )
                    tools = combined_tools.tools_schema
                    new_mcp_clients = combined_tools.mcp_clients
                    system_message = DEFAULT_SYSTEM_MESSAGE + DEFAULT_TOOLS_MESSAGE
                    tool_count = len(tools.standard_tools)
                else:
                    logger.info(
                        'Not registering tools for: {extra}',
                        extra={'service': llm_service},
                    )
                    tools = NOT_GIVEN
                    system_message = DEFAULT_SYSTEM_MESSAGE
                    tool_count = 0

                await llm_service.queue_frame(
                    LLMMessagesUpdateFrame(
                        messages=[{'role': 'system', 'content': system_message}],
                    ),
                )
                await llm_service.queue_frame(LLMSetToolsFrame(tools=tools))
            except Exception:
                await self._close_mcp_clients(new_mcp_clients)
                raise

            self._mcp_clients = new_mcp_clients
            await self._close_mcp_clients(old_mcp_clients)
            logger.info(
                'Updated LLM tools',
                extra={
                    'tools_supported': tools_supported,
                    'tool_count': tool_count,
                },
            )

    async def set_selected_service(self, id: str) -> None:
        """Queue a native Pipecat service switch from a Ubo service id."""
        target = self.service_map.get(id)
        if target is None:
            logger.warning(
                'Selected service is not available',
                extra={
                    'service_id': id,
                    'service_type': type(self).__name__,
                },
            )
            target = self._noop_service

        await cast('ServiceSwitcher', self).process_frame(
            ManuallySwitchServiceFrame(service=target),
            FrameDirection.DOWNSTREAM,
        )


class UboSwitchService(UboSwitchMixin[T], ServiceSwitcher):
    """Native ServiceSwitcher with Ubo store integration."""

    def __init__(
        self,
        client: UboRPCClient,
        *,
        selector: str,
        settings: ServiceSettings | None = None,
    ) -> None:
        """Initialize the Ubo service switcher."""
        self._noop_service = cast(
            'T',
            UboNoopService(name=f'{type(self).__name__}:noop'),
        )
        self._ubo_services = self._services
        ServiceSwitcher.__init__(
            self,
            services=cast('list[FrameProcessor]', self.switcher_services),
        )
        if settings is not None:
            self._settings = settings
        self._initialize_ubo_switch(client=client, selector=selector)


class UboLLMSwitchService(UboSwitchMixin[LLMService], LLMSwitcher):
    """Native LLMSwitcher with Ubo store integration."""

    def __init__(
        self,
        client: UboRPCClient,
        *,
        selector: str,
        settings: LLMSettings | None = None,
    ) -> None:
        """Initialize the Ubo LLM switcher."""
        self._noop_service = UboNoopLLMService()
        self._ubo_services = self._services
        LLMSwitcher.__init__(self, llms=self.switcher_services)
        if settings is not None:
            self._settings = settings
        self._initialize_ubo_switch(client=client, selector=selector)
