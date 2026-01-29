"""Tools management for the UBO Assistant service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger
from mcp.client.session_group import SseServerParameters
from mcp.client.stdio import StdioServerParameters
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.mcp_service import MCPClient

if TYPE_CHECKING:
    from pipecat.adapters.schemas.direct_function import DirectFunction
    from pipecat.services.llm_service import LLMService
    from ubo_bindings.ubo.v1 import SseMcpConfig, StdioMcpConfig


@dataclass
class MCPServerMetadata:
    """Metadata for an MCP server.

    This is a local definition that mirrors the structure
    from ubo_app.store.services.assistant.
    Since ubo-service runs in a separate virtual environment
    and communicates via gRPC, it cannot import from the core
    ubo_app package.
    """

    server_id: str  # Format: {name}_{uuid}
    name: str  # User-friendly name
    type: str  # 'stdio' or 'sse' (enum value)
    config: StdioMcpConfig | SseMcpConfig  # betterproto config from ubo_bindings


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


async def create_mcp_client_from_metadata(
    server: MCPServerMetadata,
) -> MCPClient | None:
    """Create MCP client from server metadata.

    Args:
        server: MCP server metadata with betterproto config object

    Returns:
        MCPClient instance or None if creation fails

    """
    try:
        if server.type == 'stdio':
            # STDIO configuration - config is betterproto StdioMcpConfig object
            config = server.config

            # Extract args from nested wrapper (StdioMcpConfigArgs.items)
            args_wrapper = getattr(config, 'args', None)
            if args_wrapper and hasattr(args_wrapper, 'items'):
                args = list(args_wrapper.items)
            else:
                args = []

            # Extract env from nested wrapper (StdioMcpConfigEnvDict.items)
            env_wrapper = getattr(config, 'env', None)
            if env_wrapper and hasattr(env_wrapper, 'items'):
                env = dict(env_wrapper.items)
            else:
                env = {}

            return MCPClient(
                server_params=StdioServerParameters(
                    command=config.command,
                    args=args,
                    env=env,
                ),
            )

        if server.type == 'sse':
            # SSE configuration - config is betterproto SseMcpConfig object
            config = server.config

            return MCPClient(
                server_params=SseServerParameters(
                    url=config.url,
                ),
            )

        logger.error(
            'Unknown MCP server type',
            extra={'server_id': server.server_id, 'type': server.type},
        )
    except Exception:
        logger.exception(
            'Failed to create MCP client',
            extra={'server_id': server.server_id},
        )
        return None
    else:
        return None


async def create_combined_tools(
    llm_service: LLMService,
    *,
    mcp_servers: list[MCPServerMetadata] | None = None,
) -> ToolsSchema:
    """Create combined tools schema with standard and optionally MCP tools.

    Args:
        llm_service: LLM service to register tools with
        mcp_servers: List of enabled MCP servers to load tools from

    Returns:
        ToolsSchema with combined standard and MCP tools

    """
    # Get standard tools
    ubo_standard_tools = create_ubo_standard_tools()
    combined_tools: list[FunctionSchema | DirectFunction] = []
    combined_tools.extend(ubo_standard_tools.standard_tools)

    # If no MCP servers provided, return standard tools only
    if not mcp_servers:
        return ubo_standard_tools

    # Load tools from each enabled MCP server
    for server in mcp_servers:
        try:
            logger.info(
                'Loading MCP server',
                extra={'server_id': server.server_id, 'server_name': server.name},
            )
            mcp_client = await create_mcp_client_from_metadata(server)
            if not mcp_client:
                logger.warning(
                    'Failed to create MCP client',
                    extra={'server_id': server.server_id},
                )
                continue

            # Register MCP tools
            mcp_tools = await mcp_client.register_tools(llm_service)
            combined_tools.extend(mcp_tools.standard_tools)
            logger.info(
                'Registered MCP tools',
                extra={
                    'server_id': server.server_id,
                    'tool_count': len(mcp_tools.standard_tools),
                },
            )

        except Exception:
            logger.exception(
                'Failed to load MCP server tools',
                extra={'server_id': server.server_id},
            )

    return ToolsSchema(standard_tools=combined_tools)
