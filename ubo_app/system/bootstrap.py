"""Implement `setup_service` function to set up and enable systemd service."""
from __future__ import annotations

import grp
import os
import pwd
import subprocess
from pathlib import Path
from typing import Literal, TypedDict

from ubo_app.constants import INSTALLATION_PATH, USERNAME
from ubo_app.logging import logger


class Service(TypedDict):
    """System service metadata."""

    name: str
    template: str
    scope: Literal['system', 'user']


services: list[Service] = [
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


def bootstrap() -> None:
    """Create the service files and enable the services."""
    for service in services:
        if service['scope'] == 'user':
            path = Path(f'/home/{USERNAME}/.config/systemd/user')
            path.mkdir(parents=True, exist_ok=True)
            service_file_path = (
                f'/home/{USERNAME}/.config/systemd/user/{service["name"]}.service'
            )
            while path != Path(f'/home/{USERNAME}'):
                os.chown(path, uid, gid)
                path = path.parent
        elif service['scope'] == 'system':
            service_file_path = f'/etc/systemd/system/{service["name"]}.service'
        else:
            logger.error(
                f"Service '{service['name']}' has an invalid scope: {service['scope']}",
            )
            return

        # Ensure we have the required permissions
        if os.geteuid() != 0:
            logger.error('This script needs to be run with root privileges.')
            return

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

    subprocess.run(['/usr/bin/env', 'loginctl', 'enable-linger', USERNAME], check=True)  # noqa: S603
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
    subprocess.run(
        ['/usr/bin/env', 'systemctl', 'daemon-reload'],  # noqa: S603
        check=True,
    )

    for service in services:
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
            f"Service '{service['name']}' has been created and enabled.",
        )

    with Path('/etc/polkit-1/rules.d/50-ubo.rules').open('w') as file:
        file.write(
            Path(__file__)
            .parent.joinpath('polkit-reboot.rules')
            .open()
            .read()
            .replace('{{INSTALLATION_PATH}}', INSTALLATION_PATH)
            .replace('{{USERNAME}}', USERNAME),
        )

    subprocess.run(
        [Path(__file__).parent.joinpath('install_wm8960.sh').as_posix()],  # noqa: S603
        check=True,
    )
