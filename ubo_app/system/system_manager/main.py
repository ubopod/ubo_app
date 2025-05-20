# ruff: noqa: D100, D101, D102, D103, D104, D107, PLR2004
from __future__ import annotations

import atexit
import contextlib
import grp
import logging
import os
import pwd
import socket
import stat
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from threading import Thread

from ubo_app.constants import USERNAME
from ubo_app.logger import (
    add_file_handler,
    get_log_level,
    get_logger,
)
from ubo_app.system.system_manager.audio import audio_handler
from ubo_app.system.system_manager.docker import docker_handler
from ubo_app.system.system_manager.hotspot import hotspot_handler
from ubo_app.system.system_manager.infrared import infrared_handler
from ubo_app.system.system_manager.led import LEDManager
from ubo_app.system.system_manager.package import package_handler
from ubo_app.system.system_manager.reset_button import setup_reset_button
from ubo_app.system.system_manager.service_manager import service_handler
from ubo_app.system.system_manager.update_manager import update_handler
from ubo_app.system.system_manager.users import users_handler
from ubo_app.utils.error_handlers import setup_error_handling
from ubo_app.utils.pod_id import get_pod_id, set_pod_id

SOCKET_PATH = Path(os.environ.get('RUNTIME_DIRECTORY', '/run/ubo')).joinpath(
    'system_manager.sock',
)

led_manager = LEDManager()

logger = get_logger('system-manager')
log_level = get_log_level() or logging.INFO
add_file_handler(logger, log_level)
logger.setLevel(log_level)


def handle_command(command: str, connection: socket.socket) -> None:
    try:
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
                'infrared': infrared_handler,
                'update': update_handler,
            }
            if header in handlers:
                response = handlers[header](*arguments)
                if isinstance(response, Iterator):
                    try:
                        for line in response:
                            logger.debug(
                                'Sending line to client',
                                extra={
                                    'line': line,
                                    'command': command,
                                },
                            )
                            if isinstance(line, bytes):
                                connection.sendall(line + b'\0')
                            else:
                                connection.sendall(line.encode() + b'\0')
                    finally:
                        logger.debug(
                            'Sending end of stream to client',
                            extra={
                                'command': command,
                            },
                        )
                        connection.sendall(b'\0\0')
                else:
                    logger.debug(
                        'Sending response to client',
                        extra={
                            'response': response,
                            'command': command,
                        },
                    )
                    if isinstance(response, bytes):
                        connection.sendall(response + b'\0\0')
                    elif isinstance(response, str):
                        connection.sendall(response.encode() + b'\0\0')
    except Exception as exception:
        logger.exception(
            'Failed to handle command',
            extra={
                'exception': exception,
                'command': command,
            },
        )


def setup_hostname() -> None:
    """Set the hostname to 'ubo'."""
    logger.info('Setting hostname...')

    if not get_pod_id():
        set_pod_id()

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
    logger.info('------------------Starting System Manager-------------------')

    setup_hostname()
    setup_reset_button(led_manager)

    led_manager.run_initialization_loop()

    SOCKET_PATH.unlink(missing_ok=True)
    SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)

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
    try:
        while True:
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
                    target=handle_command,
                    args=(command.decode(), connection),
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
