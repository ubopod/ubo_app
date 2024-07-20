"""Monkeypatching for tests."""

from __future__ import annotations

import random
import sys
import tracemalloc
from typing import Any, cast

import pytest


def _monkeypatch_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    from ubo_app.utils.fake import Fake

    monkeypatch.setattr(socket, 'gethostname', lambda: 'test-hostname')

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
                psutil._common.snicaddr(  # pyright: ignore [reportAttributeAccessIssue]  # noqa: SLF001
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
    from ubo_app.utils.fake import Fake

    monkeypatch.setattr(
        'docker.from_env',
        lambda: Fake(_Fake__props={'ping': Fake(_Fake__return_value=False)}),
    )


def _monkeypatch_datetime(monkeypatch: pytest.MonkeyPatch) -> None:
    import datetime

    class DateTime(datetime.datetime):
        @classmethod
        def now(cls: type[DateTime], tz: datetime.tzinfo | None = None) -> DateTime:
            _ = tz
            return DateTime(2023, 1, 1, 0, 0, 0, tzinfo=datetime.UTC)

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

    class FakeClientSession(Fake):
        def get(
            self: FakeClientSession,
            url: str,
            **kwargs: dict[str, object],
        ) -> object:
            if url == 'https://pypi.org/pypi/ubo-app/json':
                return FakeUpdateResponse()
            parent = super()
            return parent.get(url, **kwargs)

    sys.modules['aiohttp'] = Fake(_Fake__props={'ClientSession': FakeClientSession})


def _monkeypatch_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess
    from pathlib import Path

    from ubo_app.utils.fake import Fake

    original_subprocess_run = subprocess.run

    def fake_subprocess_run(
        command_: list[str | Path],
        *args: object,
        **kwargs: object,
    ) -> Fake:
        _ = args, kwargs
        here = Path().absolute()
        command = [
            c.relative_to(here).as_posix() if isinstance(c, Path) else c
            for c in command_
        ]
        if command[0] == '/usr/bin/env':
            # Setup scripts for tests
            if (
                command[1] == 'bash'
                and command[2].startswith('tests/')
                and command[2].endswith('setup.sh')
            ):
                return original_subprocess_run(command, *cast(Any, args), **kwargs)
            # Reboot and poweroff
            if command[1] == 'systemctl' and command[2] in {'reboot', 'poweroff'}:
                return Fake()
        if command[0] in {'cat', 'file'}:
            return original_subprocess_run(command, *cast(Any, args), **kwargs)
        msg = f'Unexpected `subprocess.run` command in test environment: {command}'
        raise ValueError(msg)

    monkeypatch.setattr(subprocess, 'run', fake_subprocess_run)


def _monkeypatch_asyncio_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from ubo_app.utils.fake import Fake

    class FakeAsyncProcess(Fake):
        def __init__(self: FakeAsyncProcess, output: bytes = b'') -> None:
            super().__init__(_Fake__props={'output': output})

        async def communicate(self: FakeAsyncProcess) -> tuple[bytes, bytes]:
            return cast(bytes, self.output), b''

    async def fake_create_subprocess_exec(
        command: str,
        *args: list[str],
        **kwargs: object,
    ) -> FakeAsyncProcess:
        _ = kwargs
        if command == '/usr/bin/env' and args == ('systemctl', 'is-enabled', 'ssh'):
            return FakeAsyncProcess(output=b'enabled')
        if command == '/usr/bin/env' and args == ('systemctl', 'is-active', 'ssh'):
            return FakeAsyncProcess(output=b'active')
        if command == '/usr/bin/env' and args == ('systemctl', 'is-enabled', 'lightdm'):
            return FakeAsyncProcess(output=b'enabled')
        if command == '/usr/bin/env' and args == ('systemctl', 'is-active', 'lightdm'):
            return FakeAsyncProcess(output=b'active')
        if command == '/usr/bin/env' and args == ('which', 'docker'):
            return FakeAsyncProcess(output=b'/bin/docker')
        if command == '/usr/bin/env' and args[0] == 'pulseaudio':
            return FakeAsyncProcess()
        msg = (
            'Unexpected `asyncio.create_subprocess_exec` command in test '
            f'environment: {command} - {args}'
        )
        raise ValueError(msg)

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', fake_create_subprocess_exec)
    monkeypatch.setattr(
        asyncio,
        'open_unix_connection',
        Fake(_Fake__return_value=Fake(_Fake__await_value=(Fake(), Fake()))),
    )


def _monkeypatch_asyncio_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from ubo_app.utils.fake import Fake

    monkeypatch.setattr(asyncio, 'open_connection', Fake())


@pytest.fixture()
def _monkeypatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock external resources."""
    random.seed(0)
    _monkeypatch_datetime(monkeypatch)

    import atexit
    import importlib.metadata

    import ubo_app.constants
    import ubo_app.utils.serializer
    from ubo_app.utils.fake import Fake

    tracemalloc.start()

    monkeypatch.setattr(atexit, 'register', lambda _: None)
    monkeypatch.setattr(importlib.metadata, 'version', lambda _: '0.0.0')

    monkeypatch.setattr(ubo_app.constants, 'STORE_GRACE_PERIOD', 0.1)
    monkeypatch.setattr(ubo_app.constants, 'NOTIFICATIONS_FLASH_TIME', 1000)
    monkeypatch.setattr(ubo_app.utils.serializer, 'add_type_field', lambda _, obj: obj)

    sys.modules['ubo_app.utils.secrets'] = Fake(
        _Fake__props={'read_secret': lambda _: None},
    )
    sys.modules['pyaudio'] = Fake()

    _monkeypatch_socket(monkeypatch)
    _monkeypatch_psutil(monkeypatch)
    _monkeypatch_docker(monkeypatch)
    _monkeypatch_uuid(monkeypatch)
    _monkeypatch_aiohttp()
    _monkeypatch_rpi_modules()
    _monkeypatch_subprocess(monkeypatch)
    _monkeypatch_asyncio_subprocess(monkeypatch)
    _monkeypatch_asyncio_socket(monkeypatch)


_ = _monkeypatch
