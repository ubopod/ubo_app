# ruff: noqa: D100, D103
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ubo_handle import ReducerRegistrar, register

    from ubo_app.utils.types import Subscriptions


async def setup(register_reducer: ReducerRegistrar) -> Subscriptions:
    from reducer import reducer

    register_reducer(reducer)

    from setup import init_service

    return await init_service()


def binary_env_provider() -> dict[str, str]:
    import os
    from pathlib import Path

    from constants import MCP_GATEWAY_TOKEN_SECRET_ID

    from ubo_app.constants import (
        MCP_GATEWAY_LISTEN_ADDRESS,
        MCP_GATEWAY_LISTEN_PORT,
        USERNAME,
    )

    return {
        # Prepend the ubo user's local bin dir so stdio MCP servers launched by
        # the gateway can find `uvx`/`npx` (installed there by install_uv.sh /
        # install_node.sh). The systemd --user unit sets no PATH, so this is
        # required for reliable discovery.
        'PATH': f'/home/{USERNAME}/.local/bin:' + os.environ.get('PATH', ''),
        'MCP_GATEWAY_TOKEN_SECRET_ID': MCP_GATEWAY_TOKEN_SECRET_ID,
        'MCP_GATEWAY_LISTEN_ADDRESS': MCP_GATEWAY_LISTEN_ADDRESS,
        'MCP_GATEWAY_LISTEN_PORT': str(MCP_GATEWAY_LISTEN_PORT),
        'UBO_MCP_GATEWAY_LOG_LEVEL': os.environ.get(
            'UBO_MCP_GATEWAY_LOG_LEVEL',
            'INFO',
        ),
        'UBO_MCP_GATEWAY_LOG_PATH': os.environ.get(
            'UBO_MCP_GATEWAY_LOG_PATH',
            str(Path.cwd() / 'ubo-mcp-gateway.log'),
        ),
    }


register(
    service_id='mcp',
    label='MCP',
    setup=setup,
    binary_path='bin/ubo-mcp-gateway',
    binary_env_provider=binary_env_provider,
)
