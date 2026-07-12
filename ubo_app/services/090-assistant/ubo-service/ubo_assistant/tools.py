"""Tools management for the UBO Assistant service.

MCP servers are no longer connected to individually here. They live behind the
ubo MCP gateway (a separate service); the assistant connects to that single
gateway endpoint over Streamable HTTP and inherits whatever aggregated tools it
exposes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger
from mcp.client.session_group import StreamableHttpParameters
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.mcp_service import MCPClient

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pipecat.services.llm_service import LLMService


@dataclass(frozen=True)
class CombinedTools:
    """Tools schema plus live MCP clients backing those tools."""

    tools_schema: ToolsSchema
    mcp_clients: list[MCPClient]


@dataclass(frozen=True)
class DeviceCommand:
    """One voice shortcut, as the LLM sees it.

    Mirrors the core's ``SpeechRecognitionCommandDescriptor``; kept as a plain
    dataclass so the tool schema doesn't depend on the gRPC bindings.
    """

    id: str
    label: str
    sample_phrases: tuple[str, ...] = ()


def _create_run_device_command_function(
    device_commands: Sequence[DeviceCommand],
) -> FunctionSchema:
    """Build the one generic tool that runs any configured voice shortcut.

    A single tool with an id enum, rather than one tool per command: the catalog
    is user-editable and can be long, and re-registering N handlers on every edit
    would be a lot of churn for no gain.
    """
    descriptions = '\n'.join(
        f'- {command.id}: {command.label}'
        + (
            f' (e.g. {", ".join(repr(p) for p in command.sample_phrases)})'
            if command.sample_phrases
            else ''
        )
        for command in device_commands
    )
    return FunctionSchema(
        name='run_device_command',
        description=(
            'Run one of the voice shortcuts the user has configured on their '
            'device. Use this when the user asks for something a shortcut '
            'already does, even if they phrased it differently.\n'
            f'Available commands:\n{descriptions}'
        ),
        properties={
            'command_id': {
                'type': 'string',
                'description': 'The id of the command to run.',
                'enum': [command.id for command in device_commands],
            },
        },
        required=['command_id'],
    )


def create_ubo_standard_tools(
    device_commands: Sequence[DeviceCommand] = (),
) -> ToolsSchema:
    """Create and return standard tools for the assistant.

    ``run_device_command`` is omitted entirely when no commands are configured —
    an enum with no members is not a usable schema.
    """
    draw_image_function = FunctionSchema(
        name='draw_image',
        description='Generate an image based on a text prompt.',
        properties={
            'prompt': {
                'type': 'string',
                'description': 'The text description to generate an image from.',
            },
        },
        required=['prompt'],
    )

    get_image_function = FunctionSchema(
        name='get_image',
        description='Take an image from the video stream and answer a question '
        'about it.',
        properties={
            'source': {
                'type': 'string',
                'description': 'The video stream source to take the image from. '
                'Camera captures the main camera stream, display captures what the '
                'user is seeing on their display.',
                'enum': ['camera', 'display'],
            },
            'prompt': {
                'type': 'string',
                'description': 'The question that is asked about the image.',
                'default': 'What do you see',
            },
        },
        required=['source', 'prompt'],
    )

    standard_tools = [draw_image_function, get_image_function]
    if device_commands:
        standard_tools.append(_create_run_device_command_function(device_commands))

    return ToolsSchema(standard_tools=standard_tools)


async def create_combined_tools(
    llm_service: LLMService,
    *,
    gateway_url: str | None = None,
    gateway_token: str | None = None,
    device_commands: Sequence[DeviceCommand] = (),
) -> CombinedTools:
    """Create combined tools schema with standard and gateway-provided tools.

    Args:
        llm_service: LLM service to register tools with.
        gateway_url: Streamable HTTP endpoint of the MCP gateway, or ``None`` to
            skip MCP tools (e.g. no servers enabled).
        gateway_token: Bearer token for the gateway.
        device_commands: The user's configured voice shortcuts, exposed as the
            ``run_device_command`` tool. Empty means the tool is omitted.

    Returns:
        Tools schema with standard tools plus the gateway's aggregated tools, and
        the live gateway MCP client (empty if not connected).

    """
    ubo_standard_tools = create_ubo_standard_tools(device_commands)
    combined_tools = list(ubo_standard_tools.standard_tools)
    mcp_clients: list[MCPClient] = []

    if gateway_url and gateway_token:
        try:
            mcp_client = MCPClient(
                server_params=StreamableHttpParameters(
                    url=gateway_url,
                    headers={'Authorization': f'Bearer {gateway_token}'},
                ),
            )
            await mcp_client.start()
            try:
                mcp_tools = await mcp_client.register_tools(llm_service)
            except Exception:
                await mcp_client.close()
                raise
            combined_tools.extend(mcp_tools.standard_tools)
            mcp_clients.append(mcp_client)
            logger.info(
                'Registered MCP gateway tools',
                extra={'tool_count': len(mcp_tools.standard_tools)},
            )
        except Exception:
            logger.exception('Failed to connect to MCP gateway')

    return CombinedTools(
        tools_schema=ToolsSchema(standard_tools=combined_tools),
        mcp_clients=mcp_clients,
    )
