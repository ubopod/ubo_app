"""Implement `setup_service` function to set up and enable systemd service."""

from __future__ import annotations

import grp
import os
import pwd
import random
import string
import subprocess
import time
import warnings
from pathlib import Path
from sys import stdout
from typing import Literal, TypedDict

from ubo_app.constants import INSTALLATION_PATH, USERNAME
from ubo_app.logging import logger

RETRIES = 5


class Service(TypedDict):
    """System service metadata."""

    name: str
    template: str
    scope: Literal['system', 'user']


SERVICES: list[Service] = [
    {
        'name': 'ubo-system',
        'template': 'system',
        'scope': 'system',
    },
    {
        'name': 'ubo-update',
        'template': 'update',
        'scope': 'system',
    },
    {
        'name': 'ubo-app',
        'template': 'app',
        'scope': 'user',
    },
]

uid = pwd.getpwnam(USERNAME).pw_uid
gid = grp.getgrnam(USERNAME).gr_gid


def create_user_service_directory() -> None:
    """Create the user service file."""
    path = Path(f'/home/{USERNAME}/.config/systemd/user')
    path.mkdir(parents=True, exist_ok=True)
    while path != Path(f'/home/{USERNAME}'):
        os.chown(path, uid, gid)
        path = path.parent


def setup_hostname() -> None:
    """Set the hostname to 'ubo'."""
    available_letters = list(
        set(string.ascii_lowercase + string.digits + '-') - set('IilO'),
    )

    id_path = Path(INSTALLATION_PATH) / 'id'
    if not id_path.exists():
        # Generate 2 letters random id
        id = f'ubo-{random.sample(available_letters, 2)}'
        id_path.write_text(id)

    id = id_path.read_text().strip()

    # Set hostname of the system
    Path('/etc/hostname').write_text(id)


def create_service_file(service: Service) -> None:
    """Create the service file."""
    if service['scope'] == 'user':
        service_file_path = (
            f'/home/{USERNAME}/.config/systemd/user/{service["name"]}.service'
        )
    elif service['scope'] == 'system':
        service_file_path = f'/etc/systemd/system/{service["name"]}.service'
    else:
        msg = f"Service '{service['name']}' has an invalid scope: {service['scope']}"
        logger.error(msg)
        raise ValueError(msg)

    template = (
        Path(__file__)
        .parent.joinpath(f'services/{service["template"]}.service')
        .open()
        .read()
    )

    content = template.replace(
        '{{INSTALLATION_PATH}}',
        INSTALLATION_PATH,
    ).replace(
        '{{USERNAME}}',
        USERNAME,
    )

    # Write the service content to the file
    with Path(service_file_path).open('w') as file:
        file.write(content)
        if service['scope'] == 'user':
            os.chown(service_file_path, uid, gid)


def reload_daemon() -> None:
    """Reload the systemd daemon for the user and system services."""
    logger.info('Waiting for the user services to come up...')
    for i in range(RETRIES):
        time.sleep(1)
        stdout.write('.')
        stdout.flush()
        try:
            subprocess.run(
                [  # noqa: S603
                    '/usr/bin/env',
                    'sudo',
                    f'XDG_RUNTIME_DIR=/run/user/{uid}',
                    '-u',
                    USERNAME,
                    'systemctl',
                    '--user',
                    'daemon-reload',
                ],
                check=True,
            )
        except subprocess.CalledProcessError:
            if i < RETRIES - 1:
                logger.exception('Failed to reload user services, retrying...')
                continue
        else:
            break
    else:
        msg = f'Failed to reload user services after {RETRIES} times, giving up!'
        logger.error(msg)
        warnings.warn(msg, stacklevel=2)
    stdout.flush()
    subprocess.run(
        ['/usr/bin/env', 'systemctl', 'daemon-reload'],  # noqa: S603
        check=True,
    )


def enable_services() -> None:
    """Enable the services to start on boot."""
    for service in SERVICES:
        # Enable the service to start on boot
        if service['scope'] == 'user':
            subprocess.run(
                [  # noqa: S603
                    '/usr/bin/env',
                    'sudo',
                    f'XDG_RUNTIME_DIR=/run/user/{uid}',
                    '-u',
                    USERNAME,
                    'systemctl',
                    '--user',
                    'enable',
                    service['name'],
                ],
                check=True,
            )
        elif service['scope'] == 'system':
            subprocess.run(
                ['/usr/bin/env', 'systemctl', 'enable', service['name']],  # noqa: S603
                check=True,
            )

        logger.info(
            'Service has been created and enabled.',
            extra={'service': service['name']},
        )


def configure_fan() -> None:
    """Configure the behavior of the fan."""
    if (
        'dtoverlay=gpio-fan,gpiopin=22,temp=60000'
        in Path('/boot/firmware/config.txt').read_text()
    ):
        return
    with Path('/boot/firmware/config.txt').open('a') as config_file:
        config_file.write('dtoverlay=gpio-fan,gpiopin=22,temp=60000\n')


def setup_polkit() -> None:
    """Create the polkit rules file."""
    with Path('/etc/polkit-1/rules.d/50-ubo.rules').open('w') as file:
        file.write(
            Path(__file__)
            .parent.joinpath('polkit.rules')
            .open()
            .read()
            .replace('{{INSTALLATION_PATH}}', INSTALLATION_PATH)
            .replace('{{USERNAME}}', USERNAME),
        )


def install_docker() -> None:
    """Install docker."""
    logger.info('Installing docker...')
    for i in range(RETRIES):
        time.sleep(1)
        stdout.write('.')
        stdout.flush()
        try:
            subprocess.run(
                [Path(__file__).parent.joinpath('install_docker.sh').as_posix()],  # noqa: S603
                env={'USERNAME': USERNAME},
                check=True,
            )
        except subprocess.CalledProcessError:
            if i < RETRIES - 1:
                logger.exception('Failed to install docker, retrying...')
                continue
        else:
            break
    else:
        logger.error(
            'Failed to install docker, giving up!',
            extra={'times tried': RETRIES},
        )
        return
    stdout.flush()


def install_audio_driver(*, in_packer: bool) -> None:
    """Install the audio driver."""
    stdout.write('Installing wm8960...\n')
    stdout.flush()
    subprocess.run(
        [  # noqa: S603
            Path(__file__).parent.joinpath('install_wm8960.sh').as_posix(),
        ]
        + (['--in-packer'] if in_packer else []),
        check=True,
    )
    stdout.write('Done installing wm8960\n')
    stdout.flush()


def bootstrap(*, with_docker: bool = False, in_packer: bool = False) -> None:
    """Create the service files and enable the services."""
    # Ensure we have the required permissions
    if os.geteuid() != 0:
        logger.error('This script needs to be run with root privileges.')
        return

    create_user_service_directory()
    setup_hostname()

    for service in SERVICES:
        create_service_file(service)

    if in_packer:
        Path('/var/lib/systemd/linger').mkdir(exist_ok=True, parents=True)
        Path(f'/var/lib/systemd/linger/{USERNAME}').touch(mode=0o644, exist_ok=True)
    else:
        subprocess.run(
            ['/usr/bin/env', 'loginctl', 'enable-linger', USERNAME],  # noqa: S603
            check=True,
        )

    configure_fan()

    reload_daemon()
    enable_services()

    setup_polkit()

    if with_docker:
        stdout.write('Installing docker...\n')
        stdout.flush()
        install_docker()
        stdout.write('Done installing docker\n')
        stdout.flush()

    install_audio_driver(in_packer=in_packer)
