"""Reconcile must not run twice at once.

Starting a listener dispatches a status action, and reconcile is an autorun over
the slice that status lives in — so a reconcile re-triggers itself before it has
recorded the configuration it applied. Two passes then overlap, each stopping the
listeners and rebinding the same fixed ports, and the loser fails with
``EADDRINUSE``. The runtime drops its references while the winner's socket stays
bound, so Home Assistant stays connected to a listener that no longer forwards
anything and the menu reads "Satellite: stopped".
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from ubo_app.store.services.wyoming import WyomingConnectionPolicy, WyomingState

SERVICE_DIR = (
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '090-wyoming'
)
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))


def _state(*, engines: bool) -> WyomingState:
    """Build a loopback-bound state with the satellite always enabled."""
    return WyomingState(
        is_satellite_enabled=True,
        is_engines_enabled=engines,
        connection_policy=WyomingConnectionPolicy.LOCAL_ONLY,
        allowed_peers=(),
        is_zeroconf_enabled=False,
    )


@pytest.mark.asyncio
async def test_overlapping_reconciles_keep_the_listeners() -> None:
    """An in-flight reconcile must survive a second one starting.

    This is the sequence hit by toggling the engines on: the satellite listener
    went down and stayed down, while its port remained bound.
    """
    import setup  # type: ignore[reportMissingImports]

    runtime = setup.WyomingRuntime()
    try:
        await asyncio.gather(
            runtime.reconcile(_state(engines=False)),
            runtime.reconcile(_state(engines=True)),
        )

        assert runtime._satellite is not None, 'satellite listener was dropped'  # noqa: SLF001
        assert runtime._engines is not None, 'engines listener was dropped'  # noqa: SLF001
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_a_repeated_configuration_is_still_a_no_op() -> None:
    """Serializing reconcile must not defeat the unchanged-configuration guard.

    The guard is what keeps every satellite status report off the Docker daemon,
    so it has to still short-circuit once the first pass has recorded its
    configuration.
    """
    import setup  # type: ignore[reportMissingImports]

    runtime = setup.WyomingRuntime()
    try:
        await runtime.reconcile(_state(engines=True))
        satellite = runtime._satellite  # noqa: SLF001
        engines = runtime._engines  # noqa: SLF001

        await runtime.reconcile(_state(engines=True))

        # Same objects: the second pass must not have torn anything down.
        assert runtime._satellite is satellite  # noqa: SLF001
        assert runtime._engines is engines  # noqa: SLF001
    finally:
        await runtime.close()
