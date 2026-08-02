"""Listener convergence for the Wyoming runtime."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ubo_app.store.services.wyoming import (
    WyomingAccessPolicy,
    WyomingAccessPolicyKind,
    WyomingState,
)

SERVICE_DIR = (
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '090-wyoming'
)
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))


def _docker_state() -> WyomingState:
    """Build a satellite-only state bound to the Docker bridge policy."""
    return WyomingState(
        is_satellite_enabled=True,
        is_engines_enabled=False,
        access_policies=(WyomingAccessPolicy(kind=WyomingAccessPolicyKind.DOCKER),),
        is_zeroconf_enabled=False,
    )


@pytest.mark.asyncio
async def test_unresolvable_docker_bridge_is_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A listener blocked by a not-yet-ready Docker daemon must not stay down.

    The reconcile key is remembered so unrelated status reports do not restart
    the listeners, so recording it for an attempt that never opened a socket
    would strand the service until the user toggled a setting.
    """
    import setup  # type: ignore[reportMissingImports]

    started: list[object] = []

    class _StubSatelliteServer:
        def __init__(self, **kwargs: object) -> None:
            self._kwargs = kwargs

        async def start(self) -> None:
            started.append(self._kwargs)

        async def stop(self) -> None: ...

    subnets: list[tuple[str, ...]] = [(), ('172.20.0.0/16',)]

    async def _resolve() -> tuple[str, ...]:
        return subnets.pop(0)

    monkeypatch.setattr(setup, 'SatelliteServer', _StubSatelliteServer)
    monkeypatch.setattr(setup, 'resolve_bridge_subnets', _resolve)

    runtime = setup.WyomingRuntime()
    state = _docker_state()

    await runtime.reconcile(state)
    assert not started, 'an unresolved bridge must not open a listener'

    await runtime.reconcile(state)
    assert len(started) == 1, 'the blocked listener was never retried'


@pytest.mark.asyncio
async def test_settled_configuration_is_not_restarted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Status reports re-run the autorun; they must not churn the listeners."""
    import setup  # type: ignore[reportMissingImports]

    started: list[object] = []
    resolved = 0

    class _StubSatelliteServer:
        def __init__(self, **kwargs: object) -> None:
            self._kwargs = kwargs

        async def start(self) -> None:
            started.append(self._kwargs)

        async def stop(self) -> None: ...

    async def _resolve() -> tuple[str, ...]:
        nonlocal resolved
        resolved += 1
        return ('172.20.0.0/16',)

    monkeypatch.setattr(setup, 'SatelliteServer', _StubSatelliteServer)
    monkeypatch.setattr(setup, 'resolve_bridge_subnets', _resolve)

    runtime = setup.WyomingRuntime()
    state = _docker_state()

    await runtime.reconcile(state)
    await runtime.reconcile(state)

    assert len(started) == 1
    # Re-resolving would put the Docker daemon on every satellite transition.
    assert resolved == 1
