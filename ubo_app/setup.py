"""Compatibility layer for different environments."""

from pathlib import Path
from typing import Any

import dotenv
import numpy as np


def setup() -> None:
    """Set up for different environments."""
    dotenv.load_dotenv(Path(__file__).parent / '.env')

    from ubo_app.utils import IS_RPI

    if not IS_RPI:
        import asyncio
        import subprocess
        import sys

        from ubo_app.utils.fake import Fake

        sys.modules['alsaaudio'] = Fake()
        sys.modules['pulsectl'] = Fake()
        sys.modules['sdbus'] = Fake()
        sys.modules['sdbus_async'] = Fake()
        sys.modules['sdbus_async.networkmanager'] = Fake()
        sys.modules['sdbus_async.networkmanager.enums'] = Fake()
        sys.modules['picamera2'] = Fake(
            _Fake__props={
                'Picamera2': Fake(
                    _Fake__return_value=Fake(
                        _Fake__props={
                            'capture_array': Fake(
                                _Fake__return_value=np.zeros((1, 1, 3), dtype=np.uint8),
                            ),
                        },
                    ),
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

        original_asyncio_create_subprocess_exec = asyncio.create_subprocess_exec

        def fake_create_subprocess_exec(*args: str, **kwargs: Any) -> object:  # noqa: ANN401
            command = args[0]
            if command == '/usr/bin/env':
                command = args[1]
            if isinstance(command, Path):
                command = command.as_posix()
            if any(i in command for i in ('reboot', 'poweroff')):
                return Fake()
            if command in ('curl', 'tar') or command.endswith('/code'):
                return original_asyncio_create_subprocess_exec(*args, **kwargs)
            return Fake(
                _Fake__await_value=Fake(
                    _Fake__props={
                        'communicate': Fake(
                            _Fake__return_value=Fake(_Fake__await_value=['', '']),
                        ),
                    },
                ),
            )

        asyncio.create_subprocess_exec = fake_create_subprocess_exec
