"""Implement `setup_service` function to set up and enable systemd service."""

from __future__ import annotations

import grp
import os
import pwd
import subprocess
import sys
import time
from pathlib import Path
from sys import stderr, stdout
from typing import Literal, TypedDict

from ubo_app.constants import INSTALLATION_PATH, USERNAME

RETRIES = 5


class Service(TypedDict):
    """System service metadata."""

    name: str
    scope: Literal['system', 'user']
    enabled: bool


SERVICES: list[Service] = [
    Service(name='ubo-system', scope='system', enabled=True),
    Service(name='ubo-hotspot', scope='system', enabled=False),
    Service(name='ubo-app', scope='user', enabled=True),
]

USER_UID = pwd.getpwnam(USERNAME).pw_uid
USER_GID = grp.getgrnam(USERNAME).gr_gid


def create_user_service_directory() -> None:
    """Create the user service file."""
    path = Path(f'/home/{USERNAME}/.config/systemd/user')
    path.mkdir(parents=True, exist_ok=True)
    while path != Path(f'/home/{USERNAME}'):
        os.chown(path, USER_UID, USER_GID)
        path = path.parent


def create_service_files() -> None:
    """Create the service files."""
    create_user_service_directory()
    for service in SERVICES:
        if service['scope'] == 'user':
            service_file_path = (
                f'/home/{USERNAME}/.config/systemd/user/{service["name"]}.service'
            )
        elif service['scope'] == 'system':
            service_file_path = f'/etc/systemd/system/{service["name"]}.service'
        else:
            msg = (
                f"Service '{service['name']}' has an invalid scope: {service['scope']}"
            )
            stderr.write(msg + '\n')
            stderr.flush()
            raise ValueError(msg)

        template = (
            Path(__file__)
            .parent.joinpath(f'services/{service["name"]}.service.tmpl')
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
                os.chown(service_file_path, USER_UID, USER_GID)

        if service['scope'] == 'user':
            subprocess.run(  # noqa: S603
                [
                    '/usr/bin/env',
                    'sudo',
                    f'XDG_RUNTIME_DIR=/run/user/{USER_UID}',
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
            subprocess.run(  # noqa: S603
                [
                    '/usr/bin/env',
                    'systemctl',
                    'enable' if service['enabled'] else 'disable',
                    service['name'],
                ],
                check=True,
            )

        stdout.write(f'Service {service["name"]} has been created and enabled.\n')
        stdout.flush()


def daemon_reload() -> None:
    """Reload the systemd daemon for the user and system services."""
    stdout.write('Waiting for the user services to come up...\n')
    stdout.flush()
    for i in range(RETRIES):
        time.sleep(1)
        stdout.write('.')
        stdout.flush()
        try:
            subprocess.run(  # noqa: S603
                [
                    '/usr/bin/env',
                    'sudo',
                    f'XDG_RUNTIME_DIR=/run/user/{USER_UID}',
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
                stderr.write('Failed to reload user services, retrying...\n')
                stderr.flush()
                continue
        else:
            break
    else:
        msg = f'Failed to reload user services after {RETRIES} times, giving up!'
        stderr.write(msg)
        stderr.flush()
    stdout.flush()
    subprocess.run(  # noqa: S603
        ['/usr/bin/env', 'systemctl', 'daemon-reload'],
        check=True,
    )


def configure_device() -> None:
    """Configure the device."""
    # Add the GPIO fan overlay, SPI0 CS overlay, and GPIO IR TX/RX overlays to the
    # config.txt file
    current_content = Path('/boot/firmware/config.txt').read_text()
    with Path('/boot/firmware/config.txt').open('a') as config_file:
        if 'dtoverlay=gpio-fan,gpiopin=22,temp=60000' not in current_content:
            config_file.write('dtoverlay=gpio-fan,gpiopin=22,temp=60000\n')

        if 'dtoverlay=spi0-0cs' not in current_content:
            config_file.write('dtoverlay=spi0-0cs\n')

        if 'gpio=17=op,dl' not in current_content:
            config_file.write('gpio=17=op,dl\n')

        if 'dtoverlay=gpio-ir-tx,gpio_pin=23' not in current_content:
            config_file.write('dtoverlay=gpio-ir-tx,gpio_pin=23\n')

        if 'dtoverlay=gpio-ir,gpio_pin=24' not in current_content:
            config_file.write('dtoverlay=gpio-ir,gpio_pin=24\n')

    # Remove the banner from the SSH config
    try:
        config_path = Path('/etc/ssh/sshd_config.d/rename_user.conf')
        with config_path.open('r') as file:
            lines = file.readlines()
        with config_path.open('w') as file:
            for line in lines:
                if not line.startswith('Banner '):
                    file.write(line)
    except FileNotFoundError:
        pass

    # Enable I2C and SPI interfaces
    subprocess.run(  # noqa: S603
        ['/usr/bin/env', 'raspi-config', 'nonint', 'do_i2c', '0'],
        check=True,
    )
    subprocess.run(  # noqa: S603
        ['/usr/bin/env', 'raspi-config', 'nonint', 'do_spi', '0'],
        check=True,
    )

    # Create the polkit rules file.
    with Path('/etc/polkit-1/rules.d/50-ubo.rules').open('w') as file:
        file.write(
            Path(__file__)
            .parent.joinpath('polkit.rules')
            .open()
            .read()
            .replace('{{INSTALLATION_PATH}}', INSTALLATION_PATH)
            .replace('{{USERNAME}}', USERNAME),
        )


def bootstrap(*, in_packer: bool = False) -> None:
    """Create the service files and enable the services."""
    # Ensure we have the required permissions
    if os.geteuid() != 0:
        stderr.write('This script needs to be run with root privileges.\n')
        stderr.flush()
        return

    if in_packer:
        Path('/var/lib/systemd/linger').mkdir(exist_ok=True, parents=True)
        Path(f'/var/lib/systemd/linger/{USERNAME}').touch(mode=0o644, exist_ok=True)
    else:
        subprocess.run(  # noqa: S603
            ['/usr/bin/env', 'loginctl', 'enable-linger', USERNAME],
            check=True,
        )

    configure_device()
    daemon_reload()
    create_service_files()

    # TODO(sassanh): Disable lightdm to disable piwiz to avoid its visual # noqa: FIX002
    # instructions as ubo by nature doesn't need mouse/keyboard, this is a temporary
    # solution until we have a better way to handle this.
    # Also `check` is `False` because this service is not available in the light image
    # and this same code runs for all images.
    subprocess.run(  # noqa: S603
        ['/usr/bin/env', 'systemctl', 'disable', 'lightdm'],
        check=False,
    )


def main() -> None:
    """Run the bootstrap script."""
    bootstrap(in_packer='--in-packer' in sys.argv)
    sys.stdout.write('Bootstrap completed.\n')
    sys.stdout.flush()
    sys.exit(0)
