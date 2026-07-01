"""Unit tests for the MCP gateway config translation and bearer-token auth."""

from __future__ import annotations

import asyncio
from typing import Self

import httpx
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from ubo_bindings.ubo.v1 import Action, McpServerStatus

import ubo_mcp_gateway.server as server_module
from ubo_mcp_gateway.gateway import build_mcp_config, extract_items
from ubo_mcp_gateway.server import GatewayServer, _BearerAuthMiddleware


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


class _RecordingClient:
    """Capture actions the gateway dispatches back to the store."""

    def __init__(self) -> None:
        self.actions: list[Action] = []

    def dispatch(self, *, action: Action) -> None:
        self.actions.append(action)


class _FakeClient:
    """Stand-in for ``fastmcp.Client`` as an async context manager."""

    def __init__(
        self,
        _config: object,
        *,
        raise_exc: Exception | None = None,
        tools: list | None = None,
    ) -> None:
        self._raise = raise_exc
        self._tools = tools or []

    async def __aenter__(self) -> Self:
        if self._raise is not None:
            raise self._raise
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def list_tools(self) -> list:
        return self._tools


def _server(client: _RecordingClient) -> GatewayServer:
    return GatewayServer(client=client, token='t', host='127.0.0.1', port=0)  # type: ignore[arg-type]  # noqa: S106


def _statuses(recorder: _RecordingClient) -> list[McpServerStatus]:
    return [a.mcp_set_server_status_action.status for a in recorder.actions]


def test_probe_server_reports_checking_then_healthy(
    monkeypatch: object,
) -> None:
    """A backend that lists tools transitions CHECKING → HEALTHY."""
    monkeypatch.setattr(server_module, 'Client', _FakeClient)  # type: ignore[attr-defined]
    recorder = _RecordingClient()

    asyncio.run(_server(recorder)._probe_server('a_1', {'command': 'echo'}))

    assert _statuses(recorder) == [
        McpServerStatus.CHECKING,
        McpServerStatus.HEALTHY,
    ]


def test_probe_server_reports_failed_with_message(
    monkeypatch: object,
) -> None:
    """A backend that fails to connect transitions CHECKING → FAILED (+ message)."""

    def _factory(config: object) -> _FakeClient:
        return _FakeClient(config, raise_exc=RuntimeError('spawn failed'))

    monkeypatch.setattr(server_module, 'Client', _factory)  # type: ignore[attr-defined]
    recorder = _RecordingClient()

    asyncio.run(_server(recorder)._probe_server('a_1', {'command': 'nope'}))

    assert _statuses(recorder) == [
        McpServerStatus.CHECKING,
        McpServerStatus.FAILED,
    ]
    message = recorder.actions[-1].mcp_set_server_status_action.message
    assert 'spawn failed' in (message or '')
