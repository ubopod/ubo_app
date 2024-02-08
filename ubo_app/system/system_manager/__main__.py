# ruff: noqa: D100, D101, D102, D103, D104, D107, PLR2004
from __future__ import annotations

import grp
import logging
import os
import pwd
import socket
import stat
import subprocess
import sys
from pathlib import Path
from threading import Thread
from typing import Sequence

from ubo_app.constants import DOCKER_INSTALLATION_LOCK_FILE, USERNAME
from ubo_app.logging import add_file_handler, add_stdout_handler, get_logger
from ubo_app.system.system_manager.led import LEDManager

SOCKET_PATH = Path(os.getenv('RUNTIME_DIRECTORY', '/run/ubo')).joinpath(
    'system_manager.sock',
)
# The order of the pixel colors - RGB or GRB.
# Some NeoPixels have red and green reversed!
# For RGBW NeoPixels, simply change the ORDER to RGBW or GRBW.

logger = get_logger('system-manager')
add_file_handler(logger, logging.DEBUG)
add_stdout_handler(logger, logging.DEBUG)
logger.setLevel(logging.DEBUG)
logger.debug('Initialising System-Manager...')


if __name__ == '__main__':
    led_manager = LEDManager()

    def run_led_command(incoming: Sequence[str]) -> Thread:
        logger.debug('---starting led new thread--', extra={'incoming': incoming})
        thread = Thread(target=led_manager.run_command, args=(incoming,))
        thread.start()
        return thread

    incoming = 'spinning_wheel 255 255 255 50 6 100'.split()
    thread = run_led_command(incoming)

    uid = pwd.getpwnam('root').pw_uid
    gid = grp.getgrnam(USERNAME).gr_gid

    SOCKET_PATH.unlink(missing_ok=True)

    logger.info('System Manager opening socket...')
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    server.bind(SOCKET_PATH.as_posix())
    permission = (
        stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IWGRP | stat.S_IWUSR
    )
    SOCKET_PATH.chmod(permission)

    os.chown(SOCKET_PATH, uid, gid)

    logger.info('System Manager Listening...')
    while True:
        try:
            datagram = server.recv(1024)
            if not datagram:
                break
            else:
                incoming_str = datagram.decode('utf-8')
                logger.debug('Received:', extra={'incoming_str': incoming_str})
                header, *incoming = incoming_str.split()
                if header == 'led':
                    led_manager.stop()
                    thread.join()
                    thread = run_led_command(incoming)
                elif header == 'docker':
                    # Run the install_docker.sh script
                    def install_docker(command: str) -> None:
                        Path.touch(
                            DOCKER_INSTALLATION_LOCK_FILE,
                            mode=0o666,
                            exist_ok=True,
                        )
                        try:
                            if command == 'install':
                                subprocess.run(
                                    Path(__file__)  # noqa: S603
                                    .parent.parent.joinpath('install_docker.sh')
                                    .as_posix(),
                                    env={'USERNAME': USERNAME},
                                    check=False,
                                )
                            elif command == 'start':
                                subprocess.run(
                                    [  # noqa: S603
                                        '/usr/bin/env',
                                        'systemctl',
                                        'start',
                                        'docker.socket',
                                    ],
                                    check=False,
                                )
                                subprocess.run(
                                    [  # noqa: S603
                                        '/usr/bin/env',
                                        'systemctl',
                                        'start',
                                        'docker.service',
                                    ],
                                    check=False,
                                )
                            elif command == 'stop':
                                subprocess.run(
                                    [  # noqa: S603
                                        '/usr/bin/env',
                                        'systemctl',
                                        'stop',
                                        'docker.socket',
                                    ],
                                    check=False,
                                )
                                subprocess.run(
                                    [  # noqa: S603
                                        '/usr/bin/env',
                                        'systemctl',
                                        'stop',
                                        'docker.service',
                                    ],
                                    check=False,
                                )
                        finally:
                            DOCKER_INSTALLATION_LOCK_FILE.unlink(missing_ok=True)

                    thread = Thread(target=install_docker, args=(incoming[0],))
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
