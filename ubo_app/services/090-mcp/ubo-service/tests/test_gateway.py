"""Unit tests for the MCP gateway config translation and bearer-token auth."""

from __future__ import annotations

import asyncio

import httpx
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from ubo_mcp_gateway.gateway import build_mcp_config, extract_items
from ubo_mcp_gateway.server import _BearerAuthMiddleware


class _Wrapper:
    """Wrap a payload like the betterproto ``items`` wrappers (list or dict)."""

    def __init__(self, items: object) -> None:
        self.items = items


class _Stdio:
    def __init__(self, command: str, args: list[str], env: dict[str, str]) -> None:
        self.command = command
        self.args = _Wrapper(args)
        self.env = _Wrapper(env)


class _Sse:
    def __init__(self, url: str) -> None:
        self.url = url


class _Config:
    def __init__(self, *, stdio: object = None, sse: object = None) -> None:
        self.stdio_mcp_config = stdio
        self.sse_mcp_config = sse


class _Metadata:
    def __init__(self, server_id: str, config: _Config) -> None:
        self.server_id = server_id
        self.config = config


def test_build_mcp_config_stdio_and_sse() -> None:
    """Stdio + SSE metadata translate into a FastMCP ``mcpServers`` dict."""
    items = [
        _Metadata('a_1', _Config(stdio=_Stdio('echo', ['hi'], {'K': 'V'}))),
        _Metadata('b_2', _Config(sse=_Sse('https://example.com/sse'))),
    ]

    config = build_mcp_config(items)

    assert config['mcpServers']['a_1'] == {
        'command': 'echo',
        'args': ['hi'],
        'env': {'K': 'V'},
    }
    assert config['mcpServers']['b_2'] == {
        'url': 'https://example.com/sse',
        'transport': 'sse',
    }


def test_build_mcp_config_skips_unknown() -> None:
    """A metadata with neither stdio nor sse config is skipped."""
    items = [_Metadata('x_1', _Config())]
    assert build_mcp_config(items) == {'mcpServers': {}}


def test_extract_items_unwraps_double_wrapper() -> None:
    """The selector payload is a wrapper whose ``items`` is another wrapper."""
    payload = [_Wrapper(_Wrapper(['x', 'y']))]
    assert extract_items(payload) == ['x', 'y']
    assert extract_items([]) == []


def _app_with_auth(token: str) -> Starlette:
    async def ok(_request: object) -> PlainTextResponse:
        return PlainTextResponse('ok')

    app = Starlette(routes=[Route('/ping', ok)])
    return _BearerAuthMiddleware(app, token)  # type: ignore[return-value]


def test_bearer_middleware_rejects_and_allows() -> None:
    """Requests without the exact bearer token get 401; valid ones pass."""
    token = 'sekret'  # noqa: S105

    async def _exercise() -> None:
        transport = httpx.ASGITransport(app=_app_with_auth(token))
        async with httpx.AsyncClient(
            transport=transport,
            base_url='http://test',
        ) as client:
            assert (await client.get('/ping')).status_code == 401
            bad = await client.get('/ping', headers={'Authorization': 'Bearer nope'})
            assert bad.status_code == 401
            good = await client.get(
                '/ping',
                headers={'Authorization': f'Bearer {token}'},
            )
            assert good.status_code == 200
            assert good.text == 'ok'

    asyncio.run(_exercise())
