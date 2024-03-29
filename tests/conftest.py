"""Pytest configuration file for the tests."""

from __future__ import annotations

import atexit
import datetime
import random
import sys
import tracemalloc
from pathlib import Path
from typing import cast

import dotenv
import pytest

dotenv.load_dotenv(Path(__file__).parent / '.env')

pytest.register_assert_rewrite('tests.fixtures')

# isort: off
from tests.fixtures import (  # noqa: E402
    AppContext,
    LoadServices,
    Stability,
    WindowSnapshot,
    app_context,
    load_services,
    stability,
    store,
    window_snapshot,
)

from redux_pytest.fixtures import (  # noqa: E402
    StoreMonitor,
    Waiter,
    WaitFor,
    needs_finish,
    store_monitor,
    store_snapshot,
    wait_for,
)
# isort: on


fixtures = (
    AppContext,
    LoadServices,
    Stability,
    Waiter,
    WaitFor,
    WindowSnapshot,
    StoreMonitor,
    app_context,
    load_services,
    needs_finish,
    stability,
    store,
    store_monitor,
    store_snapshot,
    wait_for,
    window_snapshot,
)


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add options to the pytest command line."""
    parser.addoption('--override-window-snapshots', action='store_true')
    parser.addoption('--make-screenshots', action='store_true')


@pytest.fixture(autouse=True)
def _logger() -> None:
    import logging

    from ubo_app.logging import ExtraFormatter

    extra_formatter = ExtraFormatter()

    for handler in logging.getLogger().handlers:
        if handler.formatter:
            handler.formatter.format = extra_formatter.format
            cast(ExtraFormatter, handler.formatter).def_keys = extra_formatter.def_keys


@pytest.fixture(autouse=True)
def _monkeypatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock external resources."""
    random.seed(0)
    tracemalloc.start()

    monkeypatch.setattr(atexit, 'register', lambda _: None)

    import socket

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

    monkeypatch.setattr(
        socket,
        'create_connection',
        lambda *args, **kwargs: Fake(args, kwargs),
    )
    original_socket_socket = socket.socket
    from ubo_app.constants import SERVER_SOCKET_PATH

    monkeypatch.setattr(
        socket,
        'socket',
        lambda *args, **kwargs: Fake(args, kwargs)
        if args[0] == SERVER_SOCKET_PATH
        else original_socket_socket(*args, **kwargs),
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

    from ubo_app.utils.fake import Fake

    counter = 0

    def debug_uuid4() -> Fake:
        nonlocal counter
        counter += 1
        import logging
        import traceback

        logging.debug(
            '`uuid.uuid4` is being called',
            extra={
                'traceback': '\n'.join(traceback.format_stack()[:-1]),
                'counter': counter,
            },
        )

        result = Fake()
        result.hex = f'{counter}'
        return result

    from ubo_app.constants import DEBUG_MODE_TEST_UUID

    if DEBUG_MODE_TEST_UUID:
        monkeypatch.setattr('uuid.uuid4', debug_uuid4)
    else:
        import uuid

        monkeypatch.setattr(
            uuid,
            'uuid4',
            lambda: uuid.UUID(int=random.getrandbits(128)),
        )

    monkeypatch.setattr('importlib.metadata.version', lambda _: '0.0.0')

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

    class FakeSensor(Fake):
        lux = 0.0
        temperature = 0.0

    class FakeSensorModule(Fake):
        PCT2075 = FakeSensor
        VEML7700 = FakeSensor

    sys.modules['adafruit_pct2075'] = FakeSensorModule()
    sys.modules['adafruit_veml7700'] = FakeSensorModule()
    sys.modules['i2c'] = Fake()


_ = fixtures, _logger, _monkeypatch
