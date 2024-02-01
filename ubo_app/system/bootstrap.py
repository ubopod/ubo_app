"""Implement `setup_service` function to set up and enable systemd service."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TypedDict

from ubo_app.constants import INSTALLATION_PATH, USERNAME
from ubo_app.logging import logger


class Service(TypedDict):
    """System service metadata."""

    name: str
    template: str


services: list[Service] = [
    {
        'name': 'ubo-led',
        'template': 'led',
    },
    {
        'name': 'ubo-update',
        'template': 'update',
    },
    {
        'name': 'ubo-app',
        'template': 'main',
    },
    {
        'name': 'ubo-pulseaudio',
        'template': 'pulseaudio',
    },
]


def bootstrap() -> None:
    """Create the service files and enable the services."""
    for service in services:
        service_file_path = f'/etc/systemd/system/{service["name"]}.service'

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

        # Enable the service to start on boot
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


def install_docker() -> None:
    """Install Docker."""
    # Run the install_docker.sh script
    subprocess.run(
        [Path(__file__).parent.joinpath('install_docker.sh').as_posix()],  # noqa: S603
        check=False,
    )
