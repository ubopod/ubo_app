"""Compatibility layer for different environments."""

from __future__ import annotations

import asyncio
import signal
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from fake import Fake
from redux import FinishAction

from ubo_app.utils import IS_TEST_ENV
from ubo_app.utils.eeprom import EMPTY_EEPROM_DATA

if TYPE_CHECKING:
    from ubo_gui.menu.types import Callable


original_subprocess_run = subprocess.run


def _fake_subprocess_run(
    command: list[str],
    *args: Any,  # noqa: ANN401
    **kwargs: Any,  # noqa: ANN401
) -> object:
    if any(i in command[0] for i in ('reboot', 'poweroff')):
        return Fake()
    return original_subprocess_run(command, *args, **kwargs)


original_asyncio_create_subprocess_exec = asyncio.create_subprocess_exec


async def _fake_create_subprocess_exec(
    *_args: str,
    **kwargs: Any,  # noqa: ANN401
) -> object:
    command = _args[0]
    args = _args[1:]

    if command == '/usr/bin/env':
        command, *args = args
    if isinstance(command, Path):
        command = command.as_posix()
    if any(i in command for i in ('reboot', 'poweroff', 'ir-ctl')):
        return Fake()
    if command in {'curl', 'tar'} or command.endswith('/code'):
        return await original_asyncio_create_subprocess_exec(*_args, **kwargs)
    if command == 'systemctl':
        if args[0] in 'is-enabled':
            return Fake(
                _Fake__return_value=Fake(_Fake__await_value=(b'enabled', b'')),
            )
        if args[0] == 'is-active':
            return Fake(
                _Fake__return_value=Fake(_Fake__await_value=(b'active', b'')),
            )
    if command == 'dpkg-query' and args[-1] in (
        'docker',
        'raspberrypi-ui-mods',
        'rpi-connect',
    ):
        return Fake(
            _Fake__return_value=Fake(_Fake__await_value=(b'install ok installed', b'')),
        )

    return await original_asyncio_create_subprocess_exec(*_args, **kwargs)


def setup() -> None:
    """Set up for different environments."""
    import sys
    import time

    from ubo_app.utils import IS_RPI

    if not IS_RPI:
        sys.modules['adafruit_irremote'] = Fake(
            _Fake__attrs={
                'GenericDecode': Fake(
                    _Fake__return_value=Fake(
                        _Fake__attrs={
                            'read_pulses': lambda *args, **kwargs: (args, kwargs)
                            and time.sleep(1),
                        },
                    ),
                ),
            },
        )
        sys.modules['adafruit_rgb_display.st7789'] = Fake()
        sys.modules['alsaaudio'] = Fake(_Fake__attrs={'cards': lambda: ['wm8960']})
        sys.modules['apt'] = Fake()
        sys.modules['board'] = Fake()
        sys.modules['digitalio'] = Fake()
        sys.modules['piper.voice'] = Fake(
            _Fake__attrs={'synthesize_stream_raw': lambda _: [b'']},
        )
        sys.modules['pulsectl'] = Fake()
        sys.modules['pulseio'] = Fake()
        sys.modules['sdbus'] = Fake()
        sys.modules['sdbus_async'] = Fake()
        sys.modules['sdbus_async.networkmanager'] = Fake()
        sys.modules['sdbus_async.networkmanager.enums'] = Fake()
        sys.modules['picamera2.picamera2'] = Fake(
            _Fake__attrs={
                'capture_array': Fake(
                    _Fake__return_value=np.zeros((1, 1, 3), dtype=np.uint8),
                ),
            },
        )
        sys.modules['sdbus.utils.inspect'] = Fake(
            _Fake__attrs={
                'inspect_dbus_path': lambda obj: obj._dbus.object_path,  # noqa: SLF001
            },
        )
        subprocess.run = _fake_subprocess_run

        asyncio.create_subprocess_exec = _fake_create_subprocess_exec

        asyncio.open_unix_connection = (
            Fake(_Fake__return_value=Fake(_Fake__await_value=(Fake(), Fake()))),
        )

        from ubo_app.utils import eeprom

        eeprom.get_eeprom_data = lambda: {
            **EMPTY_EEPROM_DATA,
            'speakers': {'model': 'wm8960'},
        }

        from ubo_app.utils import monitor_unit

        async def fake_monitor_unit(unit: str, callback: Callable[[str], None]) -> None:
            callback(
                'inactive' if unit in ('ubo-update.service') else 'active',
            )

        monitor_unit.monitor_unit = fake_monitor_unit

        from ubo_app.store.services.ethernet import NetState
        from ubo_app.utils import server

        server.send_command = lambda command, *_, has_output=False: Fake(
            _Fake__await_value={
                'connection': Fake(items=[NetState.CONNECTED]),
                'users': Fake(items=['username:password']),
            }.get(command, 'done')
            if has_output
            else 0,  # python-fake will ignore `await_value` if it is `None`
        )

        from ubo_app.utils import network

        network.has_gateway = Fake(
            _Fake__return_value=Fake(_Fake__await_value=True),
        )

    import ubo_app.display as _  # noqa: F401

    if not IS_TEST_ENV:
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

    from ubo_gui import setup as setup_ubo_gui

    setup_ubo_gui()

    from ubo_app.service import start_event_loop_thread

    start_event_loop_thread(asyncio.new_event_loop())

    from ubo_app.store.ubo_actions import register_application
    from ubo_app.utils.gui import RawContentViewer

    register_application(
        application=RawContentViewer,
        application_id='ubo:raw-content-viewer',
    )
    import ubo_app.store.main  # noqa: F401


def clear_signal_handlers() -> None:
    """Clear the signal handlers."""
    from kivy.clock import mainthread

    mainthread(_clear_signal_handlers)()


def _clear_signal_handlers() -> None:
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGUSR1, signal.SIG_DFL)


def signal_handler(signum: int, _: object) -> None:
    """Handle the signal."""
    from ubo_app.logger import logger
    from ubo_app.utils.error_handlers import get_all_thread_stacks_string

    logger.debug(get_all_thread_stacks_string())

    from ubo_app.display import display

    _clear_signal_handlers()

    logger.info('Received signal %s, turning off the display...', signum)
    display.turn_off()

    if signum == signal.SIGINT:
        logger.info('Exiting gracefully, sending the signal again will force exit!')
        from ubo_app.store.main import store

        store.dispatch(FinishAction())
    elif signum == signal.SIGTERM:
        logger.info(
            'Exiting forcefully, sending the signal again will not be caught!',
        )
        import os

        os.kill(os.getpid(), signal.SIGTERM)
