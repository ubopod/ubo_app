"""Importing a service module must not subscribe anything to the store.

A module-level `@store.autorun` registers a listener the moment the file is
imported. That leaks one per import in the unit tier — where several files load
the same service — and in production it survives an `init_service()` that fails
partway, because the cleanup is only returned on the success path.

So the subscription belongs inside the initializer, and this is the guard that
keeps it there.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.service_loader import load_service_modules
from ubo_app.store.main import store

SERVICES = Path(__file__).resolve().parents[2] / 'ubo_app' / 'services'


def _listener_count() -> int:
    return len(store._listeners)  # noqa: SLF001


@pytest.mark.parametrize(
    ('service', 'modules'),
    [
        pytest.param('040-sensors', ('menu',), id='sensors-menu'),
        pytest.param('050-mqtt', ('menu',), id='mqtt-menu'),
        pytest.param('050-mqtt', ('commands', 'client'), id='mqtt-bridge'),
        pytest.param('090-infrared', ('ha',), id='infrared-ha'),
    ],
)
def test_importing_a_service_module_subscribes_nothing(
    service: str,
    modules: tuple[str, ...],
) -> None:
    """Every listener has to be owned by an initializer that can undo it."""
    before = _listener_count()

    load_service_modules(SERVICES / service, *modules)

    assert _listener_count() == before
