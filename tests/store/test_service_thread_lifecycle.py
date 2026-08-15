"""Fast unit tests for service registration, loading, and cleanup."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from ubo_app import service_thread as service_module
from ubo_app.service_thread import DisabledServiceError, UboServiceThread
from ubo_app.store.settings.types import (
    SettingsStartServiceEvent,
    SettingsStopServiceEvent,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class _RecordingStore:
    """Store double for service-loader subscriptions and dispatches."""

    def __init__(self) -> None:
        self.subscriptions: list[tuple[type, Callable[..., object]]] = []
        self.actions: list[object] = []

    def subscribe_event(
        self,
        event_type: type,
        handler: Callable[..., object],
    ) -> None:
        """Record an event subscription."""
        self.subscriptions.append((event_type, handler))

    def dispatch(self, *actions: object) -> None:
        """Record dispatched actions."""
        self.actions.extend(actions)


def test_register_enforces_allowlist_and_records_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Registration rejects filtered IDs and stores accepted service metadata."""
    monkeypatch.setattr(service_module, 'DISABLED_SERVICES', [])
    monkeypatch.setattr(service_module, 'ENABLED_SERVICES', [])
    service = UboServiceThread(tmp_path / '090-demo', allowed_service_ids=['demo'])

    with pytest.raises(DisabledServiceError, match='blocked is disabled'):
        service.register(service_id='blocked', label='Blocked', setup=lambda: None)

    setup = lambda: None  # noqa: E731
    service.register(
        service_id='demo',
        label='Demo',
        setup=setup,
        binary_path='bin/demo',
        binary_env_provider=lambda: {'DEMO': '1'},
        is_enabled=True,
        should_auto_restart=True,
    )

    assert service.service_id == 'demo'
    assert service.label == 'Demo'
    assert service.setup is setup
    assert service.binary_path == 'bin/demo'
    assert service.is_enabled is True
    assert service.should_auto_restart is True


async def test_cleanup_runs_sync_and_async_subscriptions_and_continues_on_error(
    tmp_path: Path,
) -> None:
    """Shutdown executes every cleanup callback despite individual failures."""
    service = UboServiceThread(tmp_path / '090-demo')
    service.service_id = 'demo'
    service.label = 'Demo'
    calls: list[str] = []

    def sync_cleanup() -> None:
        calls.append('sync')

    async def async_cleanup() -> None:
        calls.append('async')

    def failing_cleanup() -> None:
        calls.append('failing')
        msg = 'cleanup failed'
        raise RuntimeError(msg)

    service.subscriptions = [sync_cleanup, async_cleanup, failing_cleanup]

    await service._clean_subscriptions()  # noqa: SLF001

    assert set(calls) == {'sync', 'async', 'failing'}
    assert not hasattr(service, 'subscriptions')


def test_cleanup_removes_thread_owned_resources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Module, service-registry, and D-Bus entries are removed together."""
    from ubo_app import utils

    service = UboServiceThread(tmp_path / '090-demo')
    service.module = ModuleType('demo')
    owned_module = f'{service.service_uid}:worker'
    bus_provider = ModuleType('ubo_app.utils.bus_provider')
    bus_provider.system_buses = {service: object()}  # type: ignore[attr-defined]
    bus_provider.user_buses = {service: object()}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, owned_module, ModuleType(owned_module))
    monkeypatch.setitem(sys.modules, 'ubo_app.utils.bus_provider', bus_provider)
    monkeypatch.setattr(utils, 'bus_provider', bus_provider, raising=False)
    monkeypatch.setattr(service_module, 'SERVICES_BY_PATH', {service.path: service})

    service._cleanup()  # noqa: SLF001

    assert service not in bus_provider.system_buses
    assert service not in bus_provider.user_buses
    assert owned_module not in sys.modules
    assert service.path not in service_module.SERVICES_BY_PATH
    assert not hasattr(service, 'module')


async def test_start_recreates_missing_service_and_starts_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A start event recreates an unloaded service from its registered path."""
    path = tmp_path / '090-demo'
    created: list[object] = []
    services: dict[Path, object] = {}

    class _Service:
        is_started = False

        def __init__(self, service_path: Path) -> None:
            self.path = service_path
            self.started = False
            created.append(self)

        def initiate(self) -> None:
            services[self.path] = self

        def start(self) -> None:
            self.started = True

    monkeypatch.setattr(service_module, 'SERVICE_PATHS_BY_ID', {'demo': path})
    monkeypatch.setattr(service_module, 'SERVICES_BY_PATH', services)
    monkeypatch.setattr(service_module, 'UboServiceThread', _Service)

    await service_module.start(SettingsStartServiceEvent(service_id='demo'))

    assert len(created) == 1
    assert cast('_Service', created[0]).started is True


def test_start_is_idempotent_against_a_racing_second_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A second ``start()`` call on the same object must not crash.

    ``threading.Thread.start`` raises if called twice on the same object.
    ``is_started`` only flips once setup finishes running on the new thread
    (see ``run``), so a real caller can't rely on it to avoid a second call
    landing here first. Reproduces the "threads can only be started once"
    regression (Sentry UBO-APP-KE).
    """
    service = UboServiceThread(tmp_path / '090-demo')
    service.setup = lambda: None
    calls: list[None] = []
    monkeypatch.setattr(
        service_module.threading.Thread,
        'start',
        lambda _self: calls.append(None),
    )

    service.start()
    service.start()

    assert len(calls) == 1


async def test_start_survives_racing_events_for_the_same_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Two concurrent restart events for one service must not crash.

    Reproduces the auto-restart race: a service reporting inactive twice
    (``SettingsServiceSetStatusAction``) before the first restart's thread
    is visibly started dispatches two ``SettingsStartServiceEvent``s. Both
    pass the module-level ``start()`` guard (``is_started`` hasn't flipped
    yet) and reach ``UboServiceThread.start()`` for the same object. Sentry
    UBO-APP-KE.
    """
    path = tmp_path / '090-demo'
    monkeypatch.setattr(service_module, 'SERVICE_PATHS_BY_ID', {'demo': path})
    monkeypatch.setattr(service_module, 'SERVICES_BY_PATH', {})
    monkeypatch.setattr(UboServiceThread, 'setup', lambda: None, raising=False)
    monkeypatch.setattr(
        UboServiceThread,
        'initiate',
        lambda self: service_module.SERVICES_BY_PATH.__setitem__(self.path, self),
    )

    thread_start_calls: list[None] = []

    def fake_thread_start(_self: object) -> None:
        if thread_start_calls:
            msg = 'threads can only be started once'
            raise RuntimeError(msg)
        thread_start_calls.append(None)

    monkeypatch.setattr(service_module.threading.Thread, 'start', fake_thread_start)

    event = SettingsStartServiceEvent(service_id='demo', delay=0)
    await asyncio.gather(service_module.start(event), service_module.start(event))

    assert len(thread_start_calls) == 1


async def test_stop_escalates_when_service_does_not_join(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A service still alive after graceful stop is killed and joined again."""
    path = tmp_path / '090-demo'

    class _Service:
        label = 'Demo'

        def __init__(self) -> None:
            self.alive = True
            self.calls: list[str] = []

        def is_alive(self) -> bool:
            return self.alive

        def stop(self) -> None:
            self.calls.append('stop')

        def join(self, *, timeout: float) -> None:
            self.calls.append(f'join:{timeout}')

        def kill(self) -> None:
            self.calls.append('kill')
            self.alive = False

    async def _to_thread(
        callback: Callable[..., object],
        *args: object,
        **kwargs: object,
    ) -> object:
        return callback(*args, **kwargs)

    service = _Service()
    monkeypatch.setattr(service_module, 'SERVICE_PATHS_BY_ID', {'demo': path})
    monkeypatch.setattr(service_module, 'SERVICES_BY_PATH', {path: service})
    monkeypatch.setattr(service_module.asyncio, 'to_thread', _to_thread)

    await service_module.stop(SettingsStopServiceEvent(service_id='demo'))

    assert service.calls == ['stop', 'join:3', 'kill', 'join:3']


def test_stop_services_respects_requested_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bulk stop leaves services outside the requested subset running."""
    first = type(
        'Service',
        (),
        {
            'service_id': 'first',
            'stop': lambda self: setattr(self, 'stopped', True),
            'stopped': False,
        },
    )()
    second = type(
        'Service',
        (),
        {
            'service_id': 'second',
            'stop': lambda self: setattr(self, 'stopped', True),
            'stopped': False,
        },
    )()
    monkeypatch.setattr(
        service_module,
        'SERVICES_BY_PATH',
        {Path('/first'): first, Path('/second'): second},
    )

    service_module.stop_services(['second'])

    assert cast('SimpleNamespace', first).stopped is False
    assert cast('SimpleNamespace', second).stopped is True


def test_reducer_barrier_suppresses_then_releases_view_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reducer startup shares one barrier and releases view computation once."""
    from ubo_app.store.core import view_computation

    calls: list[str] = []
    barriers: list[object] = []

    class _Barrier:
        def __init__(
            self,
            parties: int,
            action: Callable[[], None],
            timeout: float,
        ) -> None:
            self.parties = parties
            self.action = action
            self.timeout = timeout

    class _Service:
        def __init__(self, service_id: str) -> None:
            self.service_id = service_id

        def set_reducer_barrier(self, barrier: object, release_once: object) -> None:
            barriers.append(barrier)
            self.release_once = release_once

    services = [_Service('one'), _Service('two')]
    monkeypatch.setattr(
        view_computation,
        'suppress_view_autorun',
        lambda: calls.append('suppress'),
    )
    monkeypatch.setattr(
        view_computation,
        'release_view_autorun',
        lambda: calls.append('release'),
    )
    monkeypatch.setattr(service_module.threading, 'Barrier', _Barrier)

    service_module._setup_reducer_barrier(cast('list[UboServiceThread]', services))  # noqa: SLF001
    barrier = cast('_Barrier', barriers[0])
    barrier.action()
    barrier.action()

    assert calls == ['suppress', 'release']
    assert len(barriers) == 2
    assert barriers[0] is barriers[1]
    assert barrier.parties == 2
    assert barrier.timeout == 30


def test_load_services_applies_persisted_settings_and_dispatches_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Loading filters directories, restores settings, and seeds store state."""
    services_path = tmp_path / 'services'
    services_path.mkdir()
    (services_path / '090-alpha').mkdir()
    (services_path / '090-beta').mkdir()
    (services_path / '.cache').mkdir()
    (services_path / '~90-backup').mkdir()
    recording_store = _RecordingStore()
    fake_main = ModuleType('ubo_app.store.main')
    fake_main.store = recording_store  # type: ignore[attr-defined]
    barrier_services: list[object] = []

    class _LoadedService:
        def __init__(
            self,
            path: Path,
            *,
            allowed_service_ids: list[str] | None,
        ) -> None:
            self.path = path
            self.allowed_service_ids = allowed_service_ids
            self.service_id = path.name.split('-', maxsplit=1)[1]
            self.label = self.service_id.title()
            self.is_enabled = True
            self.should_auto_restart = False

        def initiate(self) -> None:
            if (
                self.allowed_service_ids
                and self.service_id not in self.allowed_service_ids
            ):
                return
            service_module.SERVICES_BY_PATH[self.path] = cast('UboServiceThread', self)
            service_module.SERVICE_PATHS_BY_ID[self.service_id] = self.path

        def is_alive(self) -> bool:
            return False

    from ubo_app.utils import persistent_store

    monkeypatch.setitem(sys.modules, 'ubo_app.store.main', fake_main)
    monkeypatch.setattr(service_module, 'ROOT_PATH', tmp_path)
    monkeypatch.setattr(service_module, 'SERVICES_PATH', [])
    monkeypatch.setattr(service_module, 'SERVICES_BY_PATH', {})
    monkeypatch.setattr(service_module, 'SERVICE_PATHS_BY_ID', {})
    monkeypatch.setattr(service_module, 'UboServiceThread', _LoadedService)
    monkeypatch.setattr(
        service_module,
        '_setup_reducer_barrier',
        lambda services: barrier_services.extend(services),
    )
    monkeypatch.setattr(
        persistent_store,
        'read_from_persistent_store',
        lambda *_args, **_kwargs: [
            {
                'id': 'alpha',
                'log_level': logging.DEBUG,
                'should_auto_restart': True,
            },
        ],
    )

    service_module.load_services(['alpha'], gap_duration=0.5)

    assert [event.__name__ for event, _ in recording_store.subscriptions] == [
        'SettingsStartServiceEvent',
        'SettingsStopServiceEvent',
    ]
    assert len(recording_store.actions) == 1
    action = cast('SimpleNamespace', recording_store.actions[0])
    alpha = action.services['alpha']
    assert action.gap_duration == 0.5
    assert alpha.label == 'Alpha'
    assert alpha.log_level == logging.DEBUG
    assert alpha.should_auto_restart is True
    assert [
        cast('SimpleNamespace', service).service_id for service in barrier_services
    ] == ['alpha']
