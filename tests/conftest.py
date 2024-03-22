"""Pytest configuration file for the tests."""

from __future__ import annotations

import asyncio
import atexit
import datetime
import gc
import json
import logging
import random
import socket
import sys
import tracemalloc
import uuid
import weakref
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    AsyncGenerator,
    Callable,
    Coroutine,
    Generator,
    Sequence,
    TypeAlias,
    overload,
)

import dotenv
import pytest
from tenacity import AsyncRetrying, stop_after_delay, wait_exponential

from tests.snapshot import WindowSnapshotContext, ubo_store_snapshot, window_snapshot
from ubo_app.utils.garbage_collection import examine

if TYPE_CHECKING:
    from asyncio.tasks import Task

    from _pytest.fixtures import SubRequest
    from tenacity.stop import StopBaseT
    from tenacity.wait import WaitBaseT

    from ubo_app.menu import MenuApp

pytest.register_assert_rewrite('redux.test')

dotenv.load_dotenv(Path(__file__).parent / '.test.env')


import redux.test  # noqa: E402

store_snapshot = redux.test.store_snapshot
__all__ = ('app_context', 'ubo_store_snapshot', 'window_snapshot')


def pytest_addoption(parser: pytest.Parser) -> None:
    redux.test.pytest_addoption(parser)
    parser.addoption('--override-window-snapshots', action='store_true')
    parser.addoption('--make-screenshots', action='store_true')


modules_snapshot = set(sys.modules)


@pytest.fixture(autouse=True)
def _monkeypatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock external resources."""
    random.seed(0)
    tracemalloc.start()

    monkeypatch.setattr(atexit, 'register', lambda _: None)

    import psutil

    monkeypatch.setattr(psutil, 'cpu_percent', lambda **_: 50)
    monkeypatch.setattr(
        psutil,
        'virtual_memory',
        lambda *_: type('', (object,), {'percent': 50}),
    )
    monkeypatch.setattr(
        psutil,
        'net_if_addrs',
        lambda: {
            'eth0': [
                psutil._common.snicaddr(  # noqa: SLF001 # pyright: ignore [reportAttributeAccessIssue]
                    family=socket.AddressFamily.AF_INET,
                    address='192.168.1.1',
                    netmask='255.255.255.0',
                    broadcast='192.168.1.255',
                    ptp=None,
                ),
            ],
        },
    )

    class FakeDockerClient:
        def ping(self: FakeDockerClient) -> bool:
            return False

    monkeypatch.setattr('docker.from_env', lambda: FakeDockerClient())

    class DateTime(datetime.datetime):
        @classmethod
        def now(cls: type[DateTime], tz: datetime.tzinfo | None = None) -> DateTime:
            _ = tz
            return DateTime(2023, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)

    monkeypatch.setattr(datetime, 'datetime', DateTime)
    monkeypatch.setattr(uuid, 'uuid4', lambda: uuid.UUID(int=random.getrandbits(128)))

    monkeypatch.setattr('importlib.metadata.version', lambda _: '0.0.0')

    from ubo_app.utils.fake import Fake

    class FakeUpdateResponse(Fake):
        async def json(self: FakeUpdateResponse) -> dict[str, object]:
            return {
                'info': {
                    'version': '0.0.0',
                },
            }

    class FakeAiohttp(Fake):
        def get(self: FakeAiohttp, url: str, **kwargs: dict[str, object]) -> Fake:
            if url == 'https://pypi.org/pypi/ubo-app/json':
                return FakeUpdateResponse()
            parent = super()
            return parent.get(url, **kwargs)

    sys.modules['aiohttp'] = FakeAiohttp()


class AppContext:
    """Context object for tests running a menu application."""

    def set_app(self: AppContext, app: MenuApp) -> None:
        """Set the application."""
        self.app = app
        loop = asyncio.get_event_loop()
        self.task = loop.create_task(self.app.async_run(async_lib='asyncio'))


@pytest.fixture()
async def app_context(request: SubRequest) -> AsyncGenerator[AppContext, None]:
    """Create the application."""
    import os

    os.environ['KIVY_NO_FILELOG'] = '1'
    os.environ['KIVY_NO_CONSOLELOG'] = '1'

    import headless_kivy_pi.config

    headless_kivy_pi.config.setup_headless_kivy({'automatic_fps': True})

    context = AppContext()

    yield context

    assert hasattr(context, 'task'), 'App not set for test'

    await context.task

    app_ref = weakref.ref(context.app)
    context.app.root.clear_widgets()

    del context.app
    del context.task

    gc.collect()
    app = app_ref()

    if app is not None and request.session.testsfailed == 0:
        logging.getLogger().debug(
            'Memory leak: failed to release app for test.\n'
            + json.dumps(
                {
                    'refcount': sys.getrefcount(app),
                    'referrers': gc.get_referrers(app),
                    'ref': app_ref,
                },
                sort_keys=True,
                indent=2,
                default=str,
            ),
        )
        gc.collect()
        for cell in gc.get_referrers(app):
            if type(cell).__name__ == 'cell':
                logging.getLogger().debug(
                    'CELL EXAMINATION\n' + json.dumps({'cell': cell}),
                )
                examine(cell, depth_limit=2)
        assert app is None, 'Memory leak: failed to release app for test'

    from kivy.core.window import Window

    Window.close()

    for module in set(sys.modules) - modules_snapshot:
        if module != 'objc' and 'numpy' not in module and 'cache' not in module:
            del sys.modules[module]
    gc.collect()


@pytest.fixture()
def needs_finish() -> Generator:
    yield None

    from redux import FinishAction

    from ubo_app.store import dispatch

    dispatch(FinishAction())


Waiter: TypeAlias = Callable[[], Coroutine[None, None, None]]


class WaitFor:
    def __init__(self: WaitFor) -> None:
        self.tasks: set[Task] = set()

    @overload
    def __call__(
        self: WaitFor,
        *,
        stop: StopBaseT | None = None,
        wait: WaitBaseT | None = None,
    ) -> Callable[[Callable[[], None]], Waiter]: ...

    @overload
    def __call__(
        self: WaitFor,
        check: Callable[[], None],
        *,
        stop: StopBaseT | None = None,
        wait: WaitBaseT | None = None,
    ) -> Waiter: ...

    @overload
    def __call__(
        self: WaitFor,
        *,
        timeout: float | None = None,
        wait: WaitBaseT | None = None,
    ) -> Callable[[Callable[[], None]], Waiter]: ...

    @overload
    def __call__(
        self: WaitFor,
        check: Callable[[], None],
        *,
        timeout: float | None = None,
        wait: WaitBaseT | None = None,
    ) -> Waiter: ...

    def __call__(
        self: WaitFor,
        check: Callable[[], None] | None = None,
        *,
        timeout: float | None = None,
        stop: StopBaseT | None = None,
        wait: WaitBaseT | None = None,
    ) -> Callable[[Callable[[], None]], Waiter] | Waiter:
        args = {}
        if timeout is not None:
            args['stop'] = stop_after_delay(timeout)
        elif stop:
            args['stop'] = stop

        args['wait'] = wait or wait_exponential(multiplier=0.5)

        def decorator(check: Callable[[], None]) -> Waiter:
            async def wrapper() -> None:
                async for attempt in AsyncRetrying(**args):
                    with attempt:
                        check()

            return wrapper

        if check:
            return decorator(check)

        return decorator


@pytest.fixture()
def wait_for() -> Generator[WaitFor, None, None]:
    context = WaitFor()
    yield context
    del context.tasks


LoadServices: TypeAlias = Callable[[Sequence[str]], Coroutine[None, None, None]]


@pytest.fixture()
async def load_services(wait_for: WaitFor) -> LoadServices:
    def load_services_and_wait(
        service_ids: Sequence[str],
    ) -> Coroutine[None, None, None]:
        from ubo_app.load_services import load_services

        load_services(service_ids)

        @wait_for
        def check() -> None:
            from ubo_app.load_services import REGISTERED_PATHS

            for service_id in service_ids:
                assert any(
                    service.service_id == service_id and service.is_alive()
                    for service in REGISTERED_PATHS.values()
                ), f'{service_id} not loaded'

        return check()

    return load_services_and_wait


Stability: TypeAlias = Waiter


@pytest.fixture()
async def stability(
    window_snapshot: WindowSnapshotContext,
    store_snapshot: redux.test.StoreSnapshotContext,
    wait_for: WaitFor,
) -> Waiter:
    async def wrapper() -> None:
        latest_window_hash = None
        latest_store_snapshot = None

        @wait_for
        def check() -> None:
            nonlocal latest_window_hash, latest_store_snapshot

            new_hash = window_snapshot.hash
            new_snapshot = store_snapshot.json_snapshot

            is_window_stable = latest_window_hash == new_hash
            is_store_stable = latest_store_snapshot == new_snapshot

            latest_window_hash = new_hash
            latest_store_snapshot = new_snapshot

            assert is_window_stable, 'The content of the screen is not stable yet'
            assert is_store_stable, 'The content of the store is not stable yet'

        await check()

    return wrapper
