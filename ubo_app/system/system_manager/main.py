# ruff: noqa: D100, D101, D102, D103, D104, D107, PLR2004
from __future__ import annotations

import grp
import logging
import os
import pwd
import random
import socket
import stat
import string
import subprocess
import sys
from pathlib import Path
from threading import Thread

from ubo_app.constants import USERNAME
from ubo_app.error_handlers import setup_error_handling
from ubo_app.logging import add_file_handler, add_stdout_handler, get_logger
from ubo_app.system.system_manager.audio import audio_handler
from ubo_app.system.system_manager.docker import docker_handler
from ubo_app.system.system_manager.led import LEDManager
from ubo_app.system.system_manager.package import package_handler
from ubo_app.system.system_manager.reset_button import setup_reset_button
from ubo_app.system.system_manager.service_manager import service_handler
from ubo_app.utils.eeprom import read_serial_number

SOCKET_PATH = Path(os.environ.get('RUNTIME_DIRECTORY', '/run/ubo')).joinpath(
    'system_manager.sock',
)

led_manager = LEDManager()

logger = get_logger('system-manager')
add_file_handler(logger, logging.DEBUG)
add_stdout_handler(logger, logging.DEBUG)
logger.setLevel(logging.DEBUG)


def handle_command(command: str) -> str | None:
    header, *arguments = command.split()
    if header == 'led':
        led_manager.run_command_thread_safe(arguments)
    elif header == 'docker':
        docker_handler(arguments[0])
    elif header == 'service':
        return service_handler(arguments[0], arguments[1])
    elif header == 'package':
        return package_handler(arguments[0], arguments[1])
    elif header == 'audio':
        return audio_handler(arguments[0])
    return None


def process_request(command: bytes, connection: socket.socket) -> None:
    try:
        result = handle_command(command.decode('utf-8'))
    except Exception:
        logger.exception('Failed to handle command')
        result = None
    if result is not None:
        connection.sendall(result.encode() + b'\0')


def setup_hostname() -> None:
    """Set the hostname to 'ubo'."""
    logger.debug('Setting hostname...')
    from ubo_app.constants import INSTALLATION_PATH

    available_letters = list(
        set(string.ascii_lowercase + string.digits + '-') - set('I1lO'),
    )

    id_path = Path(INSTALLATION_PATH) / 'pod-id'

    if not id_path.exists():
        serial_number = read_serial_number()
        random.seed(serial_number)
        # Generate 2 letters random id
        id = f'ubo-{"".join(random.sample(available_letters, 2))}'
        id_path.write_text(id)

    id = id_path.read_text().strip()

    # Set hostname of the system
    subprocess.run(  # noqa: S603
        [
            '/usr/bin/env',
            'hostnamectl',
            'set-hostname',
            f'{id}',
        ],
        check=True,
    )
    logger.debug('Hostname set to %s', id)


def main() -> None:
    """Initialise the System-Manager."""
    setup_error_handling()
    logger.debug('Initialising System-Manager...')

    setup_hostname()
    setup_reset_button()

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
            thread = Thread(target=process_request, args=(command, connection))
            thread.start()

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
