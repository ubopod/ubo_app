"""Setup the service."""

from __future__ import annotations

import asyncio
import contextlib
import functools
from dataclasses import fields
from pathlib import Path
from typing import TYPE_CHECKING

import docker
import docker.errors
from docker.models.containers import Container
from docker.models.images import Image
from reducer import IMAGES
from ubo_gui.constants import DANGER_COLOR
from ubo_gui.menu.types import ActionItem, HeadedMenu, HeadlessMenu, Item, SubMenuItem

from ubo_app.constants import (
    DOCKER_CREDENTIALS_TEMPLATE,
    DOCKER_INSTALLATION_LOCK_FILE,
    SERVER_SOCKET_PATH,
)
from ubo_app.store.core import (
    RegisterRegularAppAction,
    RegisterSettingAppAction,
    SettingsCategory,
)
from ubo_app.store.main import autorun, dispatch
from ubo_app.store.services.docker import (
    DockerRemoveUsernameAction,
    DockerSetStatusAction,
    DockerState,
    DockerStatus,
    DockerStoreUsernameAction,
)
from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationsAddAction,
)
from ubo_app.utils import secrets
from ubo_app.utils.async_ import create_task
from ubo_app.utils.monitor_unit import monitor_unit
from ubo_app.utils.persistent_store import register_persistent_store
from ubo_app.utils.qrcode import qrcode_input
from ubo_app.utils.server import send_command

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


def install_docker() -> None:
    """Install Docker."""
    if Path(SERVER_SOCKET_PATH).exists():

        async def act() -> None:
            await send_command('docker install')
            dispatch(DockerSetStatusAction(status=DockerStatus.INSTALLING))

        create_task(act())


def run_docker() -> None:
    """Install Docker."""

    async def act() -> None:
        await send_command('docker start')
        dispatch(DockerSetStatusAction(status=DockerStatus.UNKNOWN))

    create_task(act())


def stop_docker() -> None:
    """Install Docker."""

    async def act() -> None:
        await send_command('docker stop')
        dispatch(DockerSetStatusAction(status=DockerStatus.UNKNOWN))

    create_task(act())


async def check_docker() -> None:
    """Check if Docker is installed."""
    from image import update_container

    process = await asyncio.create_subprocess_exec(
        '/usr/bin/env',
        'which',
        'docker',
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await process.wait()
    is_installed = process.returncode == 0

    is_running = False
    with contextlib.suppress(Exception):
        docker_client = docker.from_env()
        is_running = docker_client.ping()

        for container in docker_client.containers.list(all=True):
            if not isinstance(container, Container):
                continue

            with contextlib.suppress(docker.errors.DockerException):
                container_image = container.image
                for image_id, image_description in IMAGES.items():
                    if (
                        isinstance(container_image, Image)
                        and image_description.path in container_image.tags
                    ):
                        update_container(image_id, container)

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
            placeholder='',
        )
    if status == DockerStatus.NOT_INSTALLED:
        return HeadedMenu(
            title=title,
            heading='Docker is not Installed',
            sub_heading='Install it to enjoy the power of Docker on your Ubo pod',
            items=[
                ActionItem(
                    label='Install Docker',
                    icon='󰶮',
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
            placeholder='',
        )
    if status == DockerStatus.NOT_RUNNING:
        return HeadedMenu(
            title=title,
            heading='Docker is not Running',
            sub_heading='Run it to enjoy the power of Docker on your Ubo pod',
            items=[
                ActionItem(
                    label='Start Docker',
                    icon='󰐊',
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
                    icon='󰓛',
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
            placeholder='',
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
            icon='',
            action=setup_menu_action,
        ),
    ]

    if state.service.status == DockerStatus.RUNNING:
        from image import IMAGE_MENUS

        items.append(
            SubMenuItem(
                label='Docker Containers',
                icon='󱣘',
                sub_menu=HeadlessMenu(
                    title='Docker Containers',
                    items=[
                        ActionItem(
                            label=IMAGES[image_id].label,
                            icon=IMAGES[image_id].icon,
                            action=IMAGE_MENUS[image_id],
                        )
                        for image_id in (field.name for field in fields(state))
                        if image_id not in (field.name for field in fields(DockerState))
                    ],
                    placeholder='No Docker containers',
                ),
            ),
        )

    return items


def docker_menu_item_action() -> HeadlessMenu:
    """Get the menu items for the Docker service."""
    return HeadlessMenu(
        title='󰡨Docker',
        items=docker_menu_items,
    )


docker_main_menu = ActionItem(
    label='Docker',
    icon='󰡨',
    action=docker_menu_item_action,
)


def input_credentials() -> None:
    """Input the Docker credentials."""

    async def act() -> None:
        try:
            credentials = (
                await qrcode_input(
                    r'^[^|]*\|[^|]*\|[^|]*$|^[^|]*|[^|]*$',
                    prompt='Format: [i]SERVICE|USERNAME|PASSWORD[/i]',
                    extra_information="""To generate your {QR|K Y UW AA R} code for \
login, format your details by separating your service, username, and password with the \
pipe symbol. For example, format it as "docker  {.|D AA T}io |{ |P AY P}johndoe \
|{ |P AY P}password" and then convert this text into a {QR|K Y UW AA R} code. If you \
omit the service name, "docker  {.|D AA T}io" will automatically be used as the \
default.""",
                )
            )[0]
            if credentials.count('|') == 1:
                username, password = credentials.split('|')
                registry = 'docker.io'
            else:
                registry, username, password = credentials.split('|')
            registry = registry.strip()
            username = username.strip()
            password = password.strip()
            docker_client = docker.from_env()
            docker_client.login(
                username=username,
                password=password,
                registry=registry,
            )
            secrets.write_secret(
                key=DOCKER_CREDENTIALS_TEMPLATE.format(registry),
                value=password,
            )
            dispatch(
                DockerStoreUsernameAction(registry=registry, username=username),
            )
        except asyncio.CancelledError:
            pass
        except docker.errors.APIError as exception:
            dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        title='Docker Credentials Error',
                        content='Invalid credentials',
                        extra_information=exception.explanation
                        or (
                            exception.response.content.decode('utf8')
                            if exception.response
                            else ''
                        ),
                        importance=Importance.HIGH,
                    ),
                ),
            )

    create_task(act())


def clear_credentials(registry: str) -> None:
    """Clear an entry in docker credentials."""
    secrets.clear_secret(DOCKER_CREDENTIALS_TEMPLATE.format(registry))
    dispatch(DockerRemoveUsernameAction(registry=registry))


@autorun(lambda state: state.docker.service.usernames)
def settings_menu_items(usernames: dict[str, str]) -> Sequence[Item]:
    """Get the settings menu items for the Docker service."""
    return [
        ActionItem(
            label='Add Registry',
            icon='󰌉',
            action=input_credentials,
        ),
        *(
            [
                SubMenuItem(
                    label='Registries',
                    icon='󱕴',
                    sub_menu=HeadedMenu(
                        title='󱕴Registries',
                        heading='Logged in Registries',
                        sub_heading='Log out of any registry by selecting it',
                        items=[
                            ActionItem(
                                label=registry,
                                icon='󰌊',
                                background_color=DANGER_COLOR,
                                action=functools.partial(clear_credentials, registry),
                            )
                            for registry in usernames
                        ],
                    ),
                ),
            ]
            if usernames
            else []
        ),
    ]


def init_service() -> None:
    """Initialize the service."""
    register_persistent_store(
        'docker_usernames',
        lambda state: state.docker.service.usernames,
    )
    dispatch(RegisterRegularAppAction(menu_item=docker_main_menu))
    dispatch(
        RegisterSettingAppAction(
            category=SettingsCategory.APPS,
            menu_item=SubMenuItem(
                label='Docker',
                icon='󰡨',
                sub_menu=HeadedMenu(
                    title='󰡨Docker Settings',
                    heading='󰡨 Docker',
                    sub_heading='Login a registry:',
                    items=settings_menu_items,
                ),
            ),
        ),
    )
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
