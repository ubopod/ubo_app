"""Setup the service."""
from __future__ import annotations

import asyncio
import contextlib
import socket
from dataclasses import fields
from pathlib import Path
from typing import Callable

import docker
import docker.errors
from ubo_gui.menu.types import ActionItem, HeadedMenu, HeadlessMenu, Item, SubMenuItem

from ubo_app.constants import DOCKER_INSTALLATION_LOCK_FILE, SOCKET_PATH
from ubo_app.logging import logger
from ubo_app.store import autorun, dispatch
from ubo_app.store.main import RegisterRegularAppAction
from ubo_app.store.services.docker import (
    DockerSetStatusAction,
    DockerState,
    DockerStatus,
)
from ubo_app.utils.async_ import create_task
from ubo_app.utils.monitor_unit import monitor_unit


def send_command(command: bytes) -> None:
    """Send a command to the system manager socket."""
    server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        server_socket.connect(SOCKET_PATH)
    except Exception as exception:  # noqa: BLE001
        logger.error('Unable to connect to the socket', exc_info=exception)
        return
    else:
        server_socket.send(command)
    finally:
        server_socket.close()


def install_docker() -> None:
    """Install Docker."""
    dispatch(DockerSetStatusAction(status=DockerStatus.INSTALLING))

    if Path(SOCKET_PATH).exists():
        send_command(b'docker install')


def run_docker() -> None:
    """Install Docker."""
    send_command(b'docker start')

    dispatch(DockerSetStatusAction(status=DockerStatus.UNKNOWN))


def stop_docker() -> None:
    """Install Docker."""
    send_command(b'docker stop')

    dispatch(DockerSetStatusAction(status=DockerStatus.UNKNOWN))


async def check_docker() -> None:
    """Check if Docker is installed."""
    process = await asyncio.create_subprocess_exec(
        '/usr/bin/env',
        'which',
        'docker',
    )
    await process.wait()
    is_installed = process.returncode == 0

    is_running = False
    with contextlib.suppress(Exception):
        docker_client = docker.from_env()
        is_running = docker_client.ping()
        docker_client.close()

    if is_running:
        dispatch(DockerSetStatusAction(status=DockerStatus.RUNNING))
    elif is_installed:
        dispatch(DockerSetStatusAction(status=DockerStatus.NOT_RUNNING))
    elif Path(DOCKER_INSTALLATION_LOCK_FILE).exists():
        dispatch(DockerSetStatusAction(status=DockerStatus.INSTALLING))
    else:
        dispatch(DockerSetStatusAction(status=DockerStatus.NOT_INSTALLED))


@autorun(lambda state: state.docker.service.status)
def setup_menu(status: DockerStatus) -> HeadedMenu:
    """Get the menu items for the Docker service."""
    title = 'Setup Docker'
    if status == DockerStatus.UNKNOWN:
        return HeadedMenu(
            title=title,
            heading='Checking',
            sub_heading='Checking Docker service status',
            items=[],
        )
    if status == DockerStatus.NOT_INSTALLED:
        return HeadedMenu(
            title=title,
            heading='Docker is not Installed',
            sub_heading='Install it to enjoy the power of Docker on your Ubo pod',
            items=[
                ActionItem(
                    label='Install Docker',
                    icon='system_update',
                    action=install_docker,
                ),
            ],
        )
    if status == DockerStatus.INSTALLING:
        return HeadedMenu(
            title=title,
            heading='Installing...',
            sub_heading='Docker is being installed',
            items=[],
        )
    if status == DockerStatus.NOT_RUNNING:
        return HeadedMenu(
            title=title,
            heading='Docker is not Running',
            sub_heading='Run it to enjoy the power of Docker on your Ubo pod',
            items=[
                ActionItem(
                    label='Start Docker',
                    icon='play_arrow',
                    action=run_docker,
                ),
            ],
        )
    if status == DockerStatus.RUNNING:
        return HeadedMenu(
            title=title,
            heading='Docker is Running',
            sub_heading='Enjoy the power of Docker on your Ubo pod',
            items=[
                ActionItem(
                    label='Stop Docker',
                    icon='stop',
                    action=stop_docker,
                ),
            ],
        )
    if status == DockerStatus.ERROR:
        return HeadedMenu(
            title=title,
            heading='Docker Error',
            sub_heading='Please check the logs for more information',
            items=[],
        )

    msg = f'Unknown status: {status}'
    raise ValueError(msg)


def setup_menu_action() -> Callable[[], HeadedMenu]:
    """Get the menu items for the Docker service."""
    create_task(check_docker())
    return setup_menu


@autorun(lambda state: state.docker)
def docker_menu_items(state: DockerState) -> list[Item]:
    """Get the menu items for the Docker service."""
    create_task(check_docker())
    items: list[Item] = [
        ActionItem(
            label='Setup Docker',
            icon='manufacturing',
            action=setup_menu_action,
        ),
    ]

    if state.service.status == DockerStatus.RUNNING:
        from image import image_menus

        items.append(
            SubMenuItem(
                label='Docker Containers',
                icon='category',
                sub_menu=HeadlessMenu(
                    title='Docker Containers',
                    items=[
                        ActionItem(
                            label=getattr(state, image_id).label,
                            icon=getattr(state, image_id).icon,
                            action=image_menus[image_id],
                        )
                        for image_id in (field.name for field in fields(state))
                        if image_id not in (field.name for field in fields(DockerState))
                    ],
                ),
            ),
        )

    return items


def docker_menu_item_action() -> HeadlessMenu:
    """Get the menu items for the Docker service."""
    return HeadlessMenu(
        title='Docker',
        items=docker_menu_items,
    )


docker_main_menu = ActionItem(
    label='Docker',
    icon='D',
    action=docker_menu_item_action,
)


def init_service() -> None:
    """Initialize the service."""
    dispatch(RegisterRegularAppAction(menu_item=docker_main_menu))
    create_task(
        monitor_unit(
            'docker.socket',
            lambda status: dispatch(
                DockerSetStatusAction(
                    status=DockerStatus.RUNNING
                    if status in ('active', 'activating', 'reloading')
                    else DockerStatus.NOT_RUNNING,
                ),
            ),
        ),
    )
