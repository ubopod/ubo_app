# ruff: noqa: D100, D101, D102, D103, D104, D107, PLR2004
from __future__ import annotations

import atexit
import contextlib
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
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread

from pythonping import ping

from ubo_app.constants import USERNAME
from ubo_app.error_handlers import setup_error_handling
from ubo_app.logger import (
    add_file_handler,
    get_log_level,
    get_logger,
)
from ubo_app.store.services.ethernet import NetState
from ubo_app.system.system_manager.audio import audio_handler
from ubo_app.system.system_manager.docker import docker_handler
from ubo_app.system.system_manager.hotspot import hotspot_handler
from ubo_app.system.system_manager.led import LEDManager
from ubo_app.system.system_manager.package import package_handler
from ubo_app.system.system_manager.reset_button import setup_reset_button
from ubo_app.system.system_manager.service_manager import service_handler
from ubo_app.system.system_manager.users import users_handler
from ubo_app.utils.eeprom import read_serial_number
from ubo_app.utils.pod_id import get_pod_id, set_pod_id

SOCKET_PATH = Path(os.environ.get('RUNTIME_DIRECTORY', '/run/ubo')).joinpath(
    'system_manager.sock',
)

led_manager = LEDManager()

logger = get_logger('system-manager')
log_level = get_log_level() or logging.INFO
add_file_handler(logger, log_level)
logger.setLevel(log_level)


@dataclass(kw_only=True)
class ConnectionState:
    state: NetState = NetState.UNKNOWN


connection_state = ConnectionState()

finish_event = Event()


def check_connection() -> None:
    while not finish_event.is_set():
        try:
            response = ping('1.1.1.1', timeout=1, count=1, out=None)
            connection_state.state = (
                NetState.CONNECTED if response.success() else NetState.DISCONNECTED
            )
        except OSError:
            connection_state.state = NetState.DISCONNECTED
        time.sleep(0.25)


def handle_command(command: str) -> str | None:
    header, *arguments = command.split()
    if header == 'led':
        led_manager.run_command_thread_safe(arguments)
    else:
        handlers = {
            'docker': docker_handler,
            'service': service_handler,
            'users': users_handler,
            'package': package_handler,
            'audio': audio_handler,
            'hotspot': hotspot_handler,
        }
        if header in handlers:
            return handlers[header](*arguments)
        if header == 'connection':
            return connection_state.state

    return None


def process_request(command: bytes, connection: socket.socket) -> None:
    try:
        result = handle_command(command.decode('utf-8'))
    except Exception as exception:
        logger.exception('Failed to handle command', extra={'exception': exception})
        result = None
    if result is not None:
        connection.sendall(result.encode() + b'\0')


def setup_hostname() -> None:
    """Set the hostname to 'ubo'."""
    logger.info('Setting hostname...')

    available_letters = list(
        set(string.ascii_lowercase + string.digits + '-') - set('I1lO'),
    )

    if not get_pod_id():
        serial_number = read_serial_number()
        random.seed(serial_number)
        # Generate 2 letters random id
        id = f'ubo-{"".join(random.sample(available_letters, 2))}'
        set_pod_id(id)

    id = get_pod_id()

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
    subprocess.run(  # noqa: S603
        ['/usr/bin/env', 'systemctl', 'restart', 'avahi-daemon'],
        check=True,
    )
    logger.info('Hostname set to %s', id)

    # Add it to the hosts file
    with Path('/etc/hosts').open('a+') as hosts_file:
        if f'{id}\n' not in hosts_file.read():
            hosts_file.write(f'127.0.0.1 {id}\n')
            logger.info('Added %s to /etc/hosts', id)


def _initialize() -> socket.socket:
    setup_error_handling()
    logger.info('Initialising System-Manager...')

    setup_hostname()
    setup_reset_button()

    led_manager.run_command_thread_safe(
        ['spinning_wheel', '255', '255', '255', '50', '6', '100'],
    )

    SOCKET_PATH.unlink(missing_ok=True)
    SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)

    check_connection_thread = Thread(target=check_connection, name='Check connection')
    check_connection_thread.start()

    logger.info('System Manager opening socket...')
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH.as_posix())

    atexit.register(server.close)

    server.listen()
    permission = (
        stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IWGRP | stat.S_IWUSR
    )
    SOCKET_PATH.chmod(permission)

    uid = pwd.getpwnam('root').pw_uid
    gid = grp.getgrnam(USERNAME).gr_gid
    os.chown(SOCKET_PATH, uid, gid)
    logger.info('System Manager Listening...')

    return server


def main() -> None:
    """Run the system manager."""
    server = _initialize()

    remaining = b''
    while True:
        try:
            connection, client_address = server.accept()
            try:
                logger.debug(
                    'New connection:',
                    extra={'client_address': client_address},
                )
                datagram = remaining + connection.recv(1024)
                if not datagram:
                    connection.close()
                    time.sleep(0.05)
                    continue
                if b'\0' not in datagram:
                    remaining = datagram
                    continue

                command, remaining = datagram.split(b'\0', 1)

                logger.debug('Received command:', extra={'command': command})
                thread = Thread(
                    target=process_request,
                    args=(command, connection),
                    name=f'Thread to process command {command}',
                )
                thread.start()
            except Exception:
                with contextlib.suppress(Exception):
                    if connection:
                        connection.close()
                raise

        except (KeyboardInterrupt, SystemExit):
            logger.exception('Interrupted')
            logger.info('Shutting down...')
            SOCKET_PATH.unlink()
            try:
                sys.exit(0)
            except SystemExit:
                os._exit(0)
        except Exception:
            logger.exception('Error in socket handling')
