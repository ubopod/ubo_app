"""Ubo adapters for Pipecat's native service switchers."""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast

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

from ubo_assistant.constants import (
    DEFAULT_SYSTEM_MESSAGE,
    DEFAULT_TOOLS_MESSAGE,
    LIVE_PIPELINE_SOURCE_ID,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from betterproto.lib.google.protobuf import StringValue
    from pipecat.services.mcp_service import MCPClient
    from ubo_bindings.client import UboRPCClient
    from ubo_bindings.ubo.v1 import LocationInfo, WeatherCondition

    from ubo_assistant.system_prompt_watcher import SystemPromptWatcher
    from ubo_assistant.tools import CombinedTools, DeviceCommand

T = TypeVar('T', bound=FrameProcessor)


def _compose_system_message(
    watcher: SystemPromptWatcher | None,
    *,
    include_tools: bool,
) -> str:
    """Build the system message, falling back when no watcher is wired."""
    if watcher is not None:
        return watcher.compose(include_tools=include_tools)
    if include_tools:
        return DEFAULT_SYSTEM_MESSAGE + DEFAULT_TOOLS_MESSAGE
    return DEFAULT_SYSTEM_MESSAGE


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

    def _initialize_ubo_switch(
        self,
        client: UboRPCClient,
        *,
        selector: str,
        system_prompt_watcher: SystemPromptWatcher | None = None,
    ) -> None:
        self._reset_assistance()
        self.client = client
        self._store_selector = selector
        # Only the LLM switcher composes a system message; the STT/TTS
        # switchers leave this unset.
        self._system_prompt_watcher = system_prompt_watcher
        self._unsubscribe_system_prompt: Callable[[], None] | None = None
        self._autoruns_started = False
        self._enabled_mcp_servers: set[str] = set()
        self._device_commands: list[DeviceCommand] = []
        # Latest localization state, kept fresh by an autorun. There is no
        # one-shot store read over gRPC, so the time/weather tools answer from
        # this cache.
        self._location: LocationInfo | None = None
        self._weather: WeatherCondition | None = None
        self._gateway_token: str | None = None
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
                    source_id=LIVE_PIPELINE_SOURCE_ID,
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
        if self._unsubscribe_system_prompt is not None:
            self._unsubscribe_system_prompt()
            self._unsubscribe_system_prompt = None
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
            self._setup_device_commands_autorun()
            self._setup_localization_autorun()
            if self._system_prompt_watcher is not None:
                # Re-push the system message when the user enables, edits or
                # disables a prompt, so a mid-conversation change takes effect.
                self._unsubscribe_system_prompt = (
                    self._system_prompt_watcher.subscribe(
                        self._refresh_active_llm_tools,
                    )
                )

    def _refresh_active_llm_tools(self) -> None:
        """Re-run ``_update_llm_tools`` against the currently active LLM.

        No-op unless an LLM service is actually selected and active.
        """
        if self._current_service_id is None:
            return
        native_switcher = cast('ServiceSwitcher', self)
        active_service = native_switcher.strategy.active_service
        if not isinstance(active_service, LLMService):
            return
        native_switcher.create_task(
            self._update_llm_tools(
                service_id=self._current_service_id,
                llm_service=cast('LLMService', active_service),
            ),
        )

    def _setup_localization_autorun(self) -> None:
        """Track the device's location and cached weather for the native tools.

        Unlike ``run_device_command``, the time/weather/location tools are always
        registered (they degrade gracefully when the location is unknown), so a
        change here only refreshes the cache — no tool re-registration needed.
        """

        @self.client.autorun([
            'state.localization.location',
            'state.localization.weather',
        ])
        def handle_localization_change(data: list) -> None:
            # ``None`` on the server is encoded as ``google.protobuf.Empty`` and
            # unpacks back to ``None`` here, so an unset location arrives as-is.
            self._location = data[0] if len(data) > 0 else None
            self._weather = data[1] if len(data) > 1 else None
            logger.debug(
                'Localization state changed via autorun',
                extra={
                    'has_location': self._location is not None,
                    'has_weather': self._weather is not None,
                },
            )

    def _setup_mcp_autorun(self) -> None:
        """Set up autorun subscription for MCP server state changes."""

        @self.client.autorun([
            'state.mcp.enabled_mcp_servers_with_metadata',
        ])
        def handle_mcp_servers_change(data: list) -> None:
            """Handle MCP servers state changes from Redux store."""
            self._process_mcp_servers_data(data)

    def _setup_device_commands_autorun(self) -> None:
        """Track the voice-shortcut catalog so the LLM tool follows the user's edits."""

        @self.client.autorun([
            'state.speech_recognition.commands_catalog',
        ])
        def handle_device_commands_change(data: list) -> None:
            self._process_device_commands_data(data)

    def _process_device_commands_data(self, data: list) -> None:
        """Re-register the ``run_device_command`` tool when the catalog changes.

        Mirrors ``_process_mcp_servers_data``, including its double-``items``
        unwrap: a list field inside a gRPC message arrives as a wrapper whose
        ``items`` is itself a wrapper.
        """
        from ubo_assistant.tools import DeviceCommand

        try:
            catalog_wrapper = data[0]
            items_wrapper = getattr(catalog_wrapper, 'items', None)
            if items_wrapper is None:
                descriptors = []
            else:
                descriptors = getattr(items_wrapper, 'items', [])
            if not isinstance(descriptors, list):
                descriptors = []

            device_commands = [
                DeviceCommand(
                    id=descriptor.id,
                    label=descriptor.label,
                    sample_phrases=tuple(
                        getattr(descriptor, 'sample_phrases', None) or (),
                    ),
                )
                for descriptor in descriptors
                if getattr(descriptor, 'id', None)
            ]

            logger.info(
                'Device command catalog changed via autorun',
                extra={'command_count': len(device_commands)},
            )

            self._device_commands = device_commands

            self._refresh_active_llm_tools()

        except Exception:
            logger.exception('Error handling device command catalog change')
            self._device_commands = []

    def _process_mcp_servers_data(self, data: list) -> None:
        """React to enabled-server-set changes by reconnecting to the gateway.

        The assistant no longer connects to MCP servers individually — they live
        behind the gateway. We only track *which* servers are enabled so a change
        triggers a reconnect that refreshes the aggregated tool list.
        """
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

            enabled_servers_set = {
                server_metadata.server_id
                for server_metadata in enabled_with_metadata
                if getattr(server_metadata, 'server_id', None)
            }

            logger.info(
                'MCP servers state changed via autorun',
                extra={
                    'enabled_count': len(enabled_servers_set),
                    'server_ids': list(enabled_servers_set),
                },
            )

            self._enabled_mcp_servers = enabled_servers_set

            self._refresh_active_llm_tools()

        except Exception:
            logger.exception('Error handling MCP servers state change')
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

    def _gateway_url(self) -> str:
        """Localhost Streamable HTTP endpoint of the MCP gateway."""
        port = os.environ.get('MCP_GATEWAY_LISTEN_PORT', '4322')
        return f'http://localhost:{port}/mcp'

    async def _get_gateway_token(self) -> str | None:
        """Fetch (and cache) the gateway bearer token from ubo secrets."""
        if self._gateway_token is None:
            secret_id = os.environ.get('MCP_GATEWAY_TOKEN_SECRET_ID')
            if secret_id:
                self._gateway_token = await self.client.query_secret(
                    secret_id,
                    default='',
                )
        return self._gateway_token or None

    async def _get_combined_tools(
        self,
        llm_service: LLMService[Any],
        *,
        mcp_enabled: bool = True,
    ) -> CombinedTools:
        """Get combined tools, connecting to the MCP gateway when servers exist."""
        from ubo_assistant.tools import create_combined_tools

        gateway_url: str | None = None
        gateway_token: str | None = None
        if mcp_enabled and self._enabled_mcp_servers:
            gateway_url = self._gateway_url()
            gateway_token = await self._get_gateway_token()

        logger.info(
            'Getting combined tools {extra}',
            extra={
                'mcp_enabled': mcp_enabled,
                'enabled_servers': len(self._enabled_mcp_servers),
                'gateway': bool(gateway_url and gateway_token),
                'device_commands': len(self._device_commands),
            },
        )

        combined_tools = await create_combined_tools(
            llm_service=llm_service,
            gateway_url=gateway_url,
            gateway_token=gateway_token,
            device_commands=self._device_commands,
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
        llm_service: LLMService[Any],
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
                    tool_count = len(tools.standard_tools)
                else:
                    logger.info(
                        'Not registering tools for: {extra}',
                        extra={'service': llm_service},
                    )
                    tools = NOT_GIVEN
                    tool_count = 0

                system_message = _compose_system_message(
                    self._system_prompt_watcher,
                    include_tools=tools_supported,
                )

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


class UboLLMSwitchService(UboSwitchMixin[LLMService[Any]], LLMSwitcher):
    """Native LLMSwitcher with Ubo store integration."""

    def __init__(
        self,
        client: UboRPCClient,
        *,
        selector: str,
        settings: LLMSettings | None = None,
        system_prompt_watcher: SystemPromptWatcher | None = None,
    ) -> None:
        """Initialize the Ubo LLM switcher."""
        self._noop_service = UboNoopLLMService()
        self._ubo_services = self._services
        LLMSwitcher.__init__(self, llms=self.switcher_services)
        if settings is not None:
            self._settings = settings
        self._initialize_ubo_switch(
            client=client,
            selector=selector,
            system_prompt_watcher=system_prompt_watcher,
        )
