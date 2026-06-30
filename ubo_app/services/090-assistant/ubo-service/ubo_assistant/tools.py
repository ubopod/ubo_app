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
    from pipecat.services.llm_service import LLMService


@dataclass(frozen=True)
class CombinedTools:
    """Tools schema plus live MCP clients backing those tools."""

    tools_schema: ToolsSchema
    mcp_clients: list[MCPClient]


def create_ubo_standard_tools() -> ToolsSchema:
    """Create and return standard tools for the assistant."""
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

    return ToolsSchema(standard_tools=[draw_image_function, get_image_function])


async def create_combined_tools(
    llm_service: LLMService,
    *,
    gateway_url: str | None = None,
    gateway_token: str | None = None,
) -> CombinedTools:
    """Create combined tools schema with standard and gateway-provided tools.

    Args:
        llm_service: LLM service to register tools with.
        gateway_url: Streamable HTTP endpoint of the MCP gateway, or ``None`` to
            skip MCP tools (e.g. no servers enabled).
        gateway_token: Bearer token for the gateway.

    Returns:
        Tools schema with standard tools plus the gateway's aggregated tools, and
        the live gateway MCP client (empty if not connected).

    """
    ubo_standard_tools = create_ubo_standard_tools()
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
