# ruff: noqa: D100, D101, D102, D103, D104, D107, PLR2004
from __future__ import annotations

import grp
import logging
import os
import pwd
import socket
import stat
import sys
from pathlib import Path
from threading import Thread

from ubo_app.constants import USERNAME
from ubo_app.error_handlers import setup_error_handling
from ubo_app.logging import add_file_handler, add_stdout_handler, get_logger
from ubo_app.system.system_manager.docker import docker_handler
from ubo_app.system.system_manager.led import LEDManager
from ubo_app.system.system_manager.service_manager import service_handler

SOCKET_PATH = Path(os.environ.get('RUNTIME_DIRECTORY', '/run/ubo')).joinpath(
    'system_manager.sock',
)

led_manager = LEDManager()

logger = get_logger('system-manager')
add_file_handler(logger, logging.DEBUG)
add_stdout_handler(logger, logging.DEBUG)
logger.setLevel(logging.DEBUG)


def handle_command(command: str) -> str | None:
    header, *incoming = command.split()
    if header == 'led':
        led_manager.run_command_thread_safe(incoming)
    elif header == 'docker':
        thread = Thread(target=docker_handler, args=(incoming[0],))
        thread.start()
    elif header == 'service':
        return service_handler(incoming[0], incoming[1])
    return None


def main() -> None:
    """Initialise the System-Manager."""
    setup_error_handling()
    logger.debug('Initialising System-Manager...')

    led_manager.run_command_thread_safe('spinning_wheel 255 255 255 50 6 100'.split())

    uid = pwd.getpwnam('root').pw_uid
    gid = grp.getgrnam(USERNAME).gr_gid

    SOCKET_PATH.unlink(missing_ok=True)
    SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)

    logger.info('System Manager opening socket...')
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH.as_posix())

    server.listen()
    permission = (
        stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IWGRP | stat.S_IWUSR
    )
    SOCKET_PATH.chmod(permission)

    os.chown(SOCKET_PATH, uid, gid)

    logger.info('System Manager Listening...')
    remaining = b''
    while True:
        try:
            connection, client_address = server.accept()
            logger.debug('New connection:', extra={'client_address': client_address})
            datagram = remaining + connection.recv(1024)
            if not datagram:
                break
            if b'\0' not in datagram:
                remaining = datagram
                continue

            command, remaining = datagram.split(b'\0', 1)

            logger.debug('Received command:', extra={'command': command})
            result = handle_command(command.decode('utf-8'))
            if result is not None:
                connection.sendall(result.encode() + b'\0')

        except KeyboardInterrupt:
            logger.debug('Interrupted')
            server.close()
            try:
                sys.exit(0)
            except SystemExit:
                os._exit(0)
    logger.info('Shutting down...')
    server.close()
    SOCKET_PATH.unlink()
