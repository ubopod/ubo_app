"""Tests for the MCP service reducer.

The MCP domain owns add/enable/disable/sync of MCP servers. The reducer is pure:
side effects (filesystem writes) happen in event handlers, so the reducer only
updates the slice and emits events.

The slice types are properly namespaced under ``ubo_app.store.services.mcp`` so
they're imported normally; only the reducer is loaded from the ``090-mcp``
service directory, and its bare-named service modules (``reducer`` etc.) are
removed from ``sys.modules`` afterwards so a later integration test that clears
modules isn't affected (cf. ``test_camera_reducer.py``).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

from redux import CompleteReducerResult

from ubo_app.store.services.mcp import (
    McpAddServerAction,
    McpAddServerEvent,
    McpDeleteServerAction,
    McpDeleteServerEvent,
    McpServerHealth,
    McpServerMetadata,
    McpServerStatus,
    McpServerType,
    McpSetServersAction,
    McpSetServerStatusAction,
    McpState,
    McpSyncServersAction,
    McpSyncServersEvent,
    McpToggleServerAction,
    McpToggleServerEvent,
    SseMcpConfig,
    StdioMcpConfig,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from redux import ReducerResult

    from ubo_app.store.services.mcp import McpAction, McpEvent

    Reducer = Callable[
        [McpState | None, McpAction],
        ReducerResult[McpState, McpAction, McpEvent],
    ]


def _load_reducer() -> Reducer:
    modules_before = set(sys.modules)

    service_dir = str(
        Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '090-mcp',
    )
    if service_dir not in sys.path:
        sys.path.insert(0, service_dir)

    from reducer import reducer  # type: ignore[import-not-found]

    for mod in set(sys.modules) - modules_before:
        del sys.modules[mod]

    return reducer


reducer = _load_reducer()


def _server(server_id: str, name: str) -> McpServerMetadata:
    return McpServerMetadata(
        server_id=server_id,
        name=name,
        type=McpServerType.STDIO,
        config=StdioMcpConfig(command='echo', args=['hi'], env={}),
    )


def _enabled_ids(state: McpState) -> list[str]:
    """Return the server ids in a state's ``enabled_mcp_servers_with_metadata``."""
    return [s.server_id for s in state.enabled_mcp_servers_with_metadata.items]


def test_add_server_action_emits_event() -> None:
    """Adding a server emits an event; the on-disk write happens in setup.py."""
    state = McpState()
    action = McpAddServerAction(
        name='weather',
        type=McpServerType.SSE,
        config=SseMcpConfig(url='https://example.com/sse'),
    )

    result = reducer(state, action)

    assert isinstance(result, CompleteReducerResult)
    assert result.state is state
    events = list(result.events or [])
    assert len(events) == 1
    assert isinstance(events[0], McpAddServerEvent)
    assert events[0].name == 'weather'


def test_set_servers_action_populates_state() -> None:
    """Sync result populates the dict, enabled list, and metadata wrapper."""
    state = McpState()
    servers = [_server('a_1', 'a'), _server('b_2', 'b')]
    action = McpSetServersAction(servers=servers, enabled_servers=['a_1'])

    new_state = reducer(state, action)

    assert isinstance(new_state, McpState)
    assert set(new_state.mcp_servers) == {'a_1', 'b_2'}
    assert new_state.enabled_mcp_servers == ['a_1']
    assert _enabled_ids(new_state) == ['a_1']


def test_toggle_server_flips_enabled_and_emits_event() -> None:
    """Toggling moves a server in/out of the enabled set purely."""
    state = McpState(
        mcp_servers={'a_1': _server('a_1', 'a')},
        enabled_mcp_servers=[],
    )

    result = reducer(state, McpToggleServerAction(server_id='a_1'))

    assert isinstance(result, CompleteReducerResult)
    assert result.state.enabled_mcp_servers == ['a_1']
    assert _enabled_ids(result.state) == ['a_1']
    events = list(result.events or [])
    assert isinstance(events[0], McpToggleServerEvent)

    # Toggling again disables it.
    result2 = reducer(result.state, McpToggleServerAction(server_id='a_1'))
    assert isinstance(result2, CompleteReducerResult)
    assert result2.state.enabled_mcp_servers == []


def test_delete_server_removes_and_emits_event() -> None:
    """Deleting removes the server from the dict and the enabled set."""
    state = McpState(
        mcp_servers={'a_1': _server('a_1', 'a'), 'b_2': _server('b_2', 'b')},
        enabled_mcp_servers=['a_1', 'b_2'],
    )

    result = reducer(state, McpDeleteServerAction(server_id='a_1'))

    assert isinstance(result, CompleteReducerResult)
    assert set(result.state.mcp_servers) == {'b_2'}
    assert result.state.enabled_mcp_servers == ['b_2']
    events = list(result.events or [])
    assert isinstance(events[0], McpDeleteServerEvent)


def test_sync_action_emits_sync_event() -> None:
    """Sync action only requests a filesystem reload via its event."""
    state = McpState()

    result = reducer(state, McpSyncServersAction())

    assert isinstance(result, CompleteReducerResult)
    assert result.state is state
    events = list(result.events or [])
    assert len(events) == 1
    assert isinstance(events[0], McpSyncServersEvent)


def test_set_server_status_records_health() -> None:
    """A status report is stored (with its message) for a known server."""
    state = McpState(mcp_servers={'a_1': _server('a_1', 'a')})

    healthy = reducer(
        state,
        McpSetServerStatusAction(server_id='a_1', status=McpServerStatus.HEALTHY),
    )
    assert isinstance(healthy, McpState)
    assert healthy.server_statuses['a_1'] == McpServerHealth(
        status=McpServerStatus.HEALTHY,
    )

    failed = reducer(
        healthy,
        McpSetServerStatusAction(
            server_id='a_1',
            status=McpServerStatus.FAILED,
            message='boom',
        ),
    )
    assert isinstance(failed, McpState)
    assert failed.server_statuses['a_1'] == McpServerHealth(
        status=McpServerStatus.FAILED,
        message='boom',
    )


def test_set_server_status_ignores_unknown_server() -> None:
    """A status for a server no longer configured is dropped (delete race)."""
    state = McpState()

    result = reducer(
        state,
        McpSetServerStatusAction(server_id='gone_1', status=McpServerStatus.FAILED),
    )

    assert result is state


def test_delete_prunes_stale_status() -> None:
    """Deleting a server drops its recorded health."""
    state = McpState(
        mcp_servers={'a_1': _server('a_1', 'a'), 'b_2': _server('b_2', 'b')},
        enabled_mcp_servers=['a_1'],
        server_statuses={
            'a_1': McpServerHealth(status=McpServerStatus.FAILED, message='x'),
            'b_2': McpServerHealth(status=McpServerStatus.HEALTHY),
        },
    )

    result = reducer(state, McpDeleteServerAction(server_id='a_1'))

    assert isinstance(result, CompleteReducerResult)
    assert set(result.state.server_statuses) == {'b_2'}


def test_set_servers_prunes_stale_status() -> None:
    """A filesystem re-sync drops health for servers no longer present."""
    state = McpState(
        mcp_servers={'a_1': _server('a_1', 'a')},
        server_statuses={
            'a_1': McpServerHealth(status=McpServerStatus.HEALTHY),
            'stale_9': McpServerHealth(status=McpServerStatus.FAILED),
        },
    )

    new_state = reducer(
        state,
        McpSetServersAction(servers=[_server('a_1', 'a')], enabled_servers=['a_1']),
    )

    assert isinstance(new_state, McpState)
    assert set(new_state.server_statuses) == {'a_1'}


def test_none_state_init_and_raise() -> None:
    """InitAction builds state; any other action against None raises."""
    import pytest
    from redux import InitAction, InitializationActionError

    assert isinstance(reducer(None, cast('McpAction', InitAction())), McpState)
    with pytest.raises(InitializationActionError):
        reducer(None, McpSyncServersAction())


def test_unhandled_action_returns_state_unchanged() -> None:
    """An action matching no case leaves the state untouched."""
    from redux import InitAction

    state = McpState()
    assert reducer(state, cast('McpAction', InitAction())) is state
