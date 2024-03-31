"""Monkeypatching for tests."""

from __future__ import annotations

import atexit
import datetime
import random
import sys
import tracemalloc

import pytest


def _monkeypatch_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    from ubo_app.utils.fake import Fake

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


def _monkeypatch_psutil(monkeypatch: pytest.MonkeyPatch) -> None:
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


def _monkeypatch_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeDockerClient:
        def ping(self: FakeDockerClient) -> bool:
            return False

    monkeypatch.setattr('docker.from_env', lambda: FakeDockerClient())


def _monkeypatch_datetime(monkeypatch: pytest.MonkeyPatch) -> None:
    class DateTime(datetime.datetime):
        @classmethod
        def now(cls: type[DateTime], tz: datetime.tzinfo | None = None) -> DateTime:
            _ = tz
            return DateTime(2023, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)

    monkeypatch.setattr(datetime, 'datetime', DateTime)


def _monkeypatch_uuid(monkeypatch: pytest.MonkeyPatch) -> None:
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


def _monkeypatch_rpi_modules() -> None:
    from ubo_app.utils.fake import Fake

    class FakeSensor(Fake):
        lux = 0.0
        temperature = 0.0

    class FakeSensorModule(Fake):
        PCT2075 = FakeSensor
        VEML7700 = FakeSensor

    sys.modules['adafruit_pct2075'] = FakeSensorModule()
    sys.modules['adafruit_veml7700'] = FakeSensorModule()
    sys.modules['i2c'] = Fake()


def _monkeypatch_aiohttp() -> None:
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


def _monkeypatch_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    from ubo_app.utils.fake import Fake

    def fake_subprocess_run(
        command: list[str],
        *args: object,
        **kwargs: object,
    ) -> Fake:
        _ = args, kwargs
        if command in (
            ['/usr/bin/env', 'systemctl', 'is-enabled', 'ssh'],
            ['/usr/bin/env', 'systemctl', 'is-active', 'ssh'],
        ):
            return Fake(stdout='enabled')
        if command == ['/usr/bin/env', 'systemctl', 'poweroff', '-i']:
            return Fake()
        msg = f'Unexpected `subprocess.run` command in test environment: {command}'
        raise ValueError(msg)

    monkeypatch.setattr(subprocess, 'run', fake_subprocess_run)


@pytest.fixture(autouse=True)
def _monkeypatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock external resources."""
    random.seed(0)
    tracemalloc.start()

    monkeypatch.setattr(atexit, 'register', lambda _: None)

    monkeypatch.setattr('importlib.metadata.version', lambda _: '0.0.0')

    _monkeypatch_socket(monkeypatch)
    _monkeypatch_psutil(monkeypatch)
    _monkeypatch_docker(monkeypatch)
    _monkeypatch_datetime(monkeypatch)
    _monkeypatch_uuid(monkeypatch)
    _monkeypatch_aiohttp()
    _monkeypatch_rpi_modules()
    _monkeypatch_subprocess(monkeypatch)


_ = _monkeypatch
