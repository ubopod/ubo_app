"""Compatibility layer for different environments."""

from __future__ import annotations

import signal
from pathlib import Path
from typing import Any, cast

import numpy as np
from fake import Fake
from redux import FinishAction

from ubo_app.store.main import dispatch


class _FakeAsyncProcess(Fake):
    def __init__(self: _FakeAsyncProcess, output: bytes = b'') -> None:
        super().__init__(_Fake__props={'output': output})

    async def communicate(self: _FakeAsyncProcess) -> tuple[bytes, bytes]:
        return cast(bytes, self.output), b''


def setup() -> None:
    """Set up for different environments."""
    import sys

    # it should be changed to `Fake()` and  moved inside the `if not IS_RPI` when the
    # new sdbus is released {-
    sys.modules['sdbus.utils.inspect'] = Fake(
        _Fake__props={
            'inspect_dbus_path': lambda obj: obj._dbus.object_path,  # noqa: SLF001
        },
    )
    # -}

    from ubo_app.utils import IS_RPI

    if not IS_RPI:
        import asyncio
        import subprocess

        sys.modules['adafruit_rgb_display.st7789'] = Fake()
        sys.modules['alsaaudio'] = Fake()
        sys.modules['apt'] = Fake()
        sys.modules['board'] = Fake()
        sys.modules['digitalio'] = Fake()
        sys.modules['piper.voice'] = Fake(
            _Fake__props={'synthesize_stream_raw': lambda _: [b'']},
        )
        sys.modules['pulsectl'] = Fake()
        sys.modules['sdbus'] = Fake()
        sys.modules['sdbus.utils'] = Fake()
        sys.modules['sdbus_async'] = Fake()
        sys.modules['sdbus_async.networkmanager'] = Fake()
        sys.modules['sdbus_async.networkmanager.enums'] = Fake()
        sys.modules['picamera2.picamera2'] = Fake(
            _Fake__props={
                'capture_array': Fake(
                    _Fake__return_value=np.zeros((1, 1, 3), dtype=np.uint8),
                ),
            },
        )
        original_subprocess_run = subprocess.run

        def fake_subprocess_run(
            command: list[str],
            *args: Any,  # noqa: ANN401
            **kwargs: Any,  # noqa: ANN401
        ) -> object:
            if any(i in command[0] for i in ('reboot', 'poweroff')):
                return Fake()
            return original_subprocess_run(command, *args, **kwargs)

        subprocess.run = fake_subprocess_run

        async def fake_create_subprocess_exec(
            *_args: str,
            **kwargs: Any,  # noqa: ANN401
        ) -> object:
            command = _args[0]
            args = _args[1:]

            if command == '/usr/bin/env':
                command = args[0]
                args = args[1:]
            if isinstance(command, Path):
                command = command.as_posix()
            if any(i in command for i in ('reboot', 'poweroff')):
                return Fake()
            if command in {'curl', 'tar'} or command.endswith('/code'):
                return original_asyncio_create_subprocess_exec(*args, **kwargs)

            return await original_asyncio_create_subprocess_exec(*_args, **kwargs)

        original_asyncio_create_subprocess_exec = asyncio.create_subprocess_exec

        asyncio.create_subprocess_exec = fake_create_subprocess_exec

        asyncio.open_unix_connection = (
            Fake(_Fake__return_value=Fake(_Fake__await_value=(Fake(), Fake()))),
        )

    import ubo_app.display as _  # noqa: F401

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)


def signal_handler(signum: int, _: object) -> None:
    """Handle the signal."""
    from ubo_app import display
    from ubo_app.logging import logger

    logger.info('Received signal %s, turning off the display...', signum)

    display.state.turn_off()
    display.state.pause()

    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    if signum == signal.SIGINT:
        logger.info('Exiting gracefully, sending the signal again will force exit!')
        dispatch(FinishAction())
    elif signum == signal.SIGTERM:
        logger.info(
            'Exiting forcefully, sending the signal again will not be caught!',
        )
        import os

        os.kill(os.getpid(), signal.SIGTERM)
