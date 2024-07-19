"""Compatibility layer for different environments."""

import random
import string
from pathlib import Path
from typing import Any

import dotenv
import numpy as np


def setup_hostname() -> None:
    """Set the hostname to 'ubo'."""
    from ubo_app.constants import INSTALLATION_PATH

    available_letters = list(
        set(string.ascii_lowercase + string.digits + '-') - set('I1lO'),
    )

    id_path = Path(INSTALLATION_PATH) / 'pod-id'
    if not id_path.exists():
        # Generate 2 letters random id
        id = f'ubo-{random.sample(available_letters, 2)}'
        id_path.write_text(id)

    id = id_path.read_text().strip()

    # Set hostname of the system
    Path('/etc/hostname').write_text(id, encoding='utf-8')


def setup() -> None:
    """Set up for different environments."""
    dotenv.load_dotenv(Path(__file__).parent / '.env')
    import sys

    # it should be changed to `Fake()` and  moved inside the `if not IS_RPI` when the
    # new sdbus is released {-
    from ubo_app.utils.fake import Fake

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
        sys.modules['board'] = Fake()
        sys.modules['digitalio'] = Fake()
        sys.modules['pulsectl'] = Fake()
        sys.modules['sdbus'] = Fake()
        sys.modules['sdbus.utils'] = Fake()
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
            if command in {'curl', 'tar'} or command.endswith('/code'):
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

    import ubo_app.display as _  # noqa: F401
