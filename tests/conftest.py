"""Pytest configuration file for the tests."""

from __future__ import annotations

import atexit
import datetime
import random
import socket
import sys
import tracemalloc
import uuid
from pathlib import Path

import dotenv
import pytest
from redux_pytest.fixtures import (
    StoreMonitor,
    Waiter,
    WaitFor,
    needs_finish,
    store_monitor,
    store_snapshot,
    wait_for,
)

pytest.register_assert_rewrite('tests.fixtures')

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

dotenv.load_dotenv(Path(__file__).parent / '.test.env')

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

    class FakeSensor(Fake):
        lux = 0.0
        temperature = 0.0

    class FakeSensorModule(Fake):
        PCT2075 = FakeSensor
        VEML7700 = FakeSensor

    sys.modules['adafruit_pct2075'] = FakeSensorModule()
    sys.modules['adafruit_veml7700'] = FakeSensorModule()
    sys.modules['i2c'] = Fake()


_ = fixtures, _monkeypatch
