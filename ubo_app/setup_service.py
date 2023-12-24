"""Implement `setup_service` function to set up and enable systemd service."""
import os
import subprocess
from pathlib import Path

from ubo_app.logging import logger

service_name = 'ubo_app'
service_content = """
[Install]
WantedBy=multi-user.target

[Unit]
Description=Ubo App Service
After=network.target

[Service]
User=root
ExecStart=/home/pi/ubo-app/bin/ubo
WorkingDirectory=/home/pi
StandardOutput=inherit
StandardError=inherit
Restart=always
Type=simple

[Install]
WantedBy=multi-user.target
"""


def setup_service(*, enable: bool = True, start: bool = True) -> None:
    """Create the service file and enable the service."""
    service_file_path = f'/etc/systemd/system/{service_name}.service'

    # Ensure we have the required permissions
    if os.geteuid() != 0:
        logger.error('This script needs to be run with root privileges.')
        return

    # Write the service content to the file
    with Path(service_file_path).open('w') as file:
        file.write(service_content)

    if enable:
        # Enable the service to start on boot
        subprocess.run(['/usr/bin/systemctl', 'enable', service_name], check=True)  # noqa: S603

    if start:
        # Start the service immediately
        subprocess.run(['/usr/bin/systemctl', 'start', service_name], check=True)  # noqa: S603

    logger.info(
        f"""Service '{service_name}' has been created and {
        'enabled' if enable else 'not enabled'}.""",
    )
