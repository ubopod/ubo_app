"""Tests for the MCP server on-disk storage helpers (``mcp_servers.py``).

These cover the security-sensitive filesystem layer of the ``090-mcp`` service:
that a user-controlled server name can never escape ``MCP_SERVERS_PATH`` (path
traversal), that the friendly name round-trips, and that the add path persists
purely from an ``McpAddServerEvent`` (the unified UI + gRPC write path).

The module is loaded from the ``090-mcp`` service directory the same way
``test_mcp_reducer.py`` loads the reducer; ``MCP_SERVERS_PATH`` is redirected to
a ``tmp_path`` so no real filesystem is touched.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ubo_app.store.services.mcp import (
    McpAddServerEvent,
    McpServerType,
    SseMcpConfig,
    StdioMcpConfig,
)

if TYPE_CHECKING:
    from types import ModuleType


def _load_mcp_servers_module() -> ModuleType:
    modules_before = set(sys.modules)

    service_dir = str(
        Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '090-mcp',
    )
    if service_dir not in sys.path:
        sys.path.insert(0, service_dir)

    import mcp_servers  # type: ignore[import-not-found]

    for mod in set(sys.modules) - modules_before:
        del sys.modules[mod]

    return mcp_servers


mcp_servers = _load_mcp_servers_module()


@pytest.fixture
def store_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Redirect the module's MCP_SERVERS_PATH to an isolated tmp directory."""
    servers_path = tmp_path / 'mcp_servers'
    servers_path.mkdir()
    monkeypatch.setattr(mcp_servers, 'MCP_SERVERS_PATH', servers_path)
    return servers_path


def test_save_sanitizes_malicious_name(store_path: Path) -> None:
    """A traversal-laden name yields a safe id confined under MCP_SERVERS_PATH."""
    server_id = mcp_servers.save_mcp_server(
        '../../etc/evil',
        McpServerType.STDIO,
        StdioMcpConfig(command='echo', args=['hi'], env={}),
    )

    assert '/' not in server_id
    assert '..' not in server_id

    server_dir = (store_path / server_id).resolve()
    assert server_dir.is_relative_to(store_path.resolve())
    # The write landed inside the config dir, not outside it.
    assert (server_dir / 'config.json').exists()
    assert list(store_path.iterdir()) == [store_path / server_id]


def test_save_restricts_secret_file_permissions(store_path: Path) -> None:
    """A saved config can hold env secrets, so dir is 0o700 and config 0o600."""
    server_id = mcp_servers.save_mcp_server(
        'Secretful',
        McpServerType.STDIO,
        StdioMcpConfig(command='echo', args=[], env={'API_KEY': 'super-secret'}),
    )

    server_dir = store_path / server_id
    config_file = server_dir / 'config.json'

    assert server_dir.stat().st_mode & 0o777 == 0o700
    assert config_file.stat().st_mode & 0o777 == 0o600


def test_resolve_server_dir_rejects_traversal(store_path: Path) -> None:
    """The confinement resolver refuses ids that escape MCP_SERVERS_PATH."""
    _ = store_path
    with pytest.raises(ValueError, match='outside the config directory'):
        mcp_servers._resolve_server_dir('../escape')  # noqa: SLF001


def test_delete_refuses_traversal(store_path: Path) -> None:
    """delete_mcp_server must not rmtree outside MCP_SERVERS_PATH."""
    victim = store_path.parent / 'victim'
    victim.mkdir()

    with pytest.raises(ValueError, match='outside the config directory'):
        mcp_servers.delete_mcp_server('../victim')

    assert victim.exists()  # untouched


def test_save_load_roundtrips_friendly_name(store_path: Path) -> None:
    """The friendly name is persisted and restored verbatim (not slugified)."""
    _ = store_path
    mcp_servers.save_mcp_server(
        'My Weather Server',
        McpServerType.SSE,
        SseMcpConfig(url='https://example.com/sse'),
    )

    loaded = mcp_servers.load_mcp_servers()

    assert len(loaded) == 1
    metadata = next(iter(loaded.values()))
    assert metadata.name == 'My Weather Server'
    assert isinstance(metadata.config, SseMcpConfig)
    assert metadata.config.url == 'https://example.com/sse'


def test_add_event_fields_persist_via_save(store_path: Path) -> None:
    """An McpAddServerEvent carries everything the add handler needs to persist.

    Mirrors the unified write path: handle_add_mcp_server calls
    save_mcp_server(event.name, event.type, event.config), so a non-UI (gRPC)
    dispatch persists identically to the UI.
    """
    _ = store_path
    event = McpAddServerEvent(
        name='grpc client',
        type=McpServerType.STDIO,
        config=StdioMcpConfig(command='uvx', args=['some-mcp'], env={'K': 'v'}),
    )

    mcp_servers.save_mcp_server(event.name, event.type, event.config)

    loaded = mcp_servers.load_mcp_servers()
    assert len(loaded) == 1
    metadata = next(iter(loaded.values()))
    assert metadata.name == 'grpc client'
    assert isinstance(metadata.config, StdioMcpConfig)
    assert metadata.config.command == 'uvx'
    assert metadata.config.args == ['some-mcp']
    assert metadata.config.env == {'K': 'v'}
