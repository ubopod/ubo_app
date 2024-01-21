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
    content: str


services: list[Service] = [
    {
        'name': 'ubo-led',
        'content': Path(__file__).parent.joinpath('led.service').open().read(),
    },
    {
        'name': 'ubo-update',
        'content': Path(__file__).parent.joinpath('update.service').open().read(),
    },
    {
        'name': 'ubo-app',
        'content': Path(__file__).parent.joinpath('main.service').open().read(),
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

        # Write the service content to the file
        with Path(service_file_path).open('w') as file:
            file.write(
                service['content']
                .replace('{{INSTALLATION_PATH}}', INSTALLATION_PATH)
                .replace('{{USERNAME}}', USERNAME),
            )

        # Enable the service to start on boot
        subprocess.run(
            ['/usr/bin/env', 'systemctl', 'enable', service['name']],  # noqa: S603
            check=True,
        )

        logger.info(
            f"Service '{service['name']}' has been created and enabled.",
        )

    with Path('/etc/polkit-1/rules.d/50-reboot.rules').open('w') as file:
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
