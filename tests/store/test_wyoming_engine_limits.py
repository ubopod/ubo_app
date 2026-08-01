"""Cancellation behavior for Wyoming engine request admission."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

SERVICE_DIR = (
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '090-wyoming'
)
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))


@pytest.mark.asyncio
async def test_cancelled_engine_request_does_not_wait_for_a_slot() -> None:
    """A disconnect leaves no queued assistant work behind it."""
    from assistant_bridge import AssistantBridge  # type: ignore[reportMissingImports]
    from engines import (  # type: ignore[reportMissingImports]
        EngineRequestCancelledError,
        EnginesServer,
    )
    from security import PeerAccess  # type: ignore[reportMissingImports]

    from ubo_app.store.services.wyoming import WyomingConnectionPolicy

    server = EnginesServer(
        host='127.0.0.1',
        port=0,
        access=PeerAccess(policy=WyomingConnectionPolicy.LOCAL_ONLY),
        bridge=AssistantBridge(),
    )
    server._requests = asyncio.Semaphore(0)  # noqa: SLF001
    cancelled = asyncio.Event()
    cancelled.set()

    with pytest.raises(EngineRequestCancelledError):
        async with server.request_slot(cancelled):
            pytest.fail('Cancelled requests must not receive a work slot')

    assert server._active_requests == 0  # noqa: SLF001


@pytest.mark.asyncio
async def test_stopped_server_keeps_stopped_status_while_requests_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A late request cleanup must not revive a listener that was stopped."""
    import engines  # type: ignore[reportMissingImports]
    from assistant_bridge import AssistantBridge  # type: ignore[reportMissingImports]
    from engines import EnginesServer  # type: ignore[reportMissingImports]
    from security import PeerAccess  # type: ignore[reportMissingImports]

    from ubo_app.store.services.wyoming import (
        WyomingConnectionPolicy,
        WyomingEnginesStatus,
    )

    dispatched: list[object] = []
    monkeypatch.setattr(engines.store, 'dispatch', dispatched.append)
    server = EnginesServer(
        host='127.0.0.1',
        port=0,
        access=PeerAccess(policy=WyomingConnectionPolicy.LOCAL_ONLY),
        bridge=AssistantBridge(),
    )
    server._active_requests = 1  # noqa: SLF001

    await server.stop()
    server._report_status()  # noqa: SLF001

    assert dispatched[-1].status is WyomingEnginesStatus.STOPPED  # type: ignore[attr-defined]
