"""Tests for when the sensors service writes what it knows to disk.

Two ways the persisted device list can be destroyed, both of which turn a
transient problem into a permanent one: persisting before the restore has
landed (the autorun fires on its initial, empty value), and treating a failed
bus scan as a successful empty one.

The gate is in the *selector* rather than in when the autorun is registered,
because registering it later means registering it from a coroutine — and
shutdown can run in between, leaving an autorun bound to a service that has
already been cleaned up.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fake import Fake

from tests.service_loader import load_service_modules
from ubo_app.store.services.sensors import (
    SensorDeviceState,
    SensorsState,
    SensorStatus,
)

# `setup` opens the I2C bus at import; off-device the app fakes `board` in
# `setup_headless`, and the test environment has to do the same.
sys.modules.setdefault('board', Fake())

(setup,) = load_service_modules(
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '040-sensors',
    'setup',
)


def _device() -> SensorDeviceState:
    return SensorDeviceState(
        id='sht4x_0x44',
        definition_id='sht4x',
        label='SHT4x',
        address=0x44,
        is_builtin=False,
        status=SensorStatus.ACTIVE,
    )


def _persisted(*devices: SensorDeviceState) -> str | None:
    """Return what the persistence autorun would write for this state."""
    return setup.persistence_selector(
        SimpleNamespace(
            sensors=SensorsState(devices={device.id: device for device in devices}),
        ),
    )


@pytest.fixture(autouse=True)
def _disarmed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test where a freshly started service starts."""
    monkeypatch.setattr(setup, '_is_armed', False)


@pytest.fixture
def dispatched(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Collect dispatched actions instead of driving the real store."""
    actions: list[Any] = []
    monkeypatch.setattr(
        setup.store,
        'dispatch',
        lambda *args: actions.extend(args),
    )
    # Reaches for the running service, which does not exist under pytest.
    monkeypatch.setattr(setup, 'report_service_error', lambda *_, **__: None)
    return actions


def _completions(actions: list[Any]) -> list[Any]:
    return [
        action
        for action in actions
        if type(action).__name__ == 'SensorsScanCompletedAction'
    ]


def test_nothing_is_written_until_the_restore_has_landed() -> None:
    """A `None` is what `register_persistent_store` skips.

    The autorun is live from `init_service`, so without this the empty
    start-up state would be written over the list the restore is still reading
    back in the worker thread.
    """
    assert _persisted() is None
    assert _persisted(_device()) is None


async def test_a_successful_restore_arms_persistence(
    monkeypatch: pytest.MonkeyPatch,
    dispatched: list[Any],
) -> None:
    """And it arms *before* dispatching, since the dispatch re-runs the autorun."""
    device = _device()

    async def _restores(task: object, *_: object, **__: object) -> object:
        if task is setup._activate_persisted:  # noqa: SLF001
            # Nothing may be writable before the restored list is in the store.
            assert _persisted(device) is None
            return (device,)
        return {}

    monkeypatch.setattr(setup.WORKER, 'run', _restores)

    await setup._initialize()  # noqa: SLF001

    assert [action.devices for action in _completions(dispatched)] == [(device,)]
    assert json.loads(_persisted(device) or '') == [
        {'definition_id': 'sht4x', 'address': 0x44},
    ]


async def test_a_failed_restore_leaves_persistence_disarmed(
    monkeypatch: pytest.MonkeyPatch,
    dispatched: list[Any],
) -> None:
    """The file keeps what it had; nothing has been learned to replace it with.

    And the failure must not escape: `_initialize` runs as a fire-and-forget
    task, so a raise here would silently disable the whole service. It settles
    the scan state with `devices=None` — "keep what you have" — instead.
    """

    async def _fails(*_: object, **__: object) -> None:
        msg = 'bus fell over'
        raise OSError(msg)

    monkeypatch.setattr(setup.WORKER, 'run', _fails)

    await setup._initialize()  # noqa: SLF001

    assert [action.devices for action in _completions(dispatched)] == [None]
    assert _persisted() is None


async def test_a_failed_scan_keeps_the_registry_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    dispatched: list[Any],
) -> None:
    """A bus error must not reach the store as "nothing is plugged in".

    Persisting that would survive the reboot the user tries next, and the
    entities would already be gone from Home Assistant by then.
    """

    async def _fails(*_: object, **__: object) -> None:
        msg = 'bus fell over'
        raise OSError(msg)

    monkeypatch.setattr(setup.WORKER, 'run', _fails)

    await setup.scan_sensors()

    assert [action.devices for action in _completions(dispatched)] == [None]
    assert _persisted(_device()) is None


async def test_a_successful_scan_arms_persistence(
    monkeypatch: pytest.MonkeyPatch,
    dispatched: list[Any],
) -> None:
    """An empty bus *is* an answer, and it is the one worth remembering."""

    async def _finds_nothing(*_: object, **__: object) -> tuple[object, ...]:
        return ()

    monkeypatch.setattr(setup.WORKER, 'run', _finds_nothing)

    await setup.scan_sensors()

    assert [action.devices for action in _completions(dispatched)] == [()]
    assert _persisted() == '[]'


@pytest.mark.usefixtures('dispatched')
async def test_stopping_the_service_disarms_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A restarted instance must go through its own restore before writing.

    The flag is module state, and a service restart in the same process may
    reuse this module.
    """

    async def _finds_nothing(*_: object, **__: object) -> tuple[object, ...]:
        return ()

    monkeypatch.setattr(setup.WORKER, 'run', _finds_nothing)
    await setup.scan_sensors()
    assert _persisted() == '[]'

    setup._disarm_persistence()  # noqa: SLF001

    assert _persisted() is None
