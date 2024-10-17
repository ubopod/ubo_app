"""Setup the service."""

from __future__ import annotations

import asyncio
import contextlib
import functools
from typing import TYPE_CHECKING, cast

import docker
import docker.errors
from docker.models.containers import Container
from docker.models.images import Image
from image_menus import IMAGE_MENUS
from reducer import IMAGES
from ubo_gui.constants import DANGER_COLOR
from ubo_gui.menu.types import ActionItem, HeadedMenu, Item, SubMenuItem

from ubo_app.constants import DOCKER_CREDENTIALS_TEMPLATE
from ubo_app.store.core import (
    RegisterRegularAppAction,
    RegisterSettingAppAction,
    SettingsCategory,
)
from ubo_app.store.main import store
from ubo_app.store.operations import InputFieldDescription, InputFieldType
from ubo_app.store.services.docker import (
    DockerImageRegisterAppEvent,
    DockerRemoveUsernameAction,
    DockerSetStatusAction,
    DockerStatus,
    DockerStoreUsernameAction,
)
from ubo_app.store.services.notifications import (
    Chime,
    Importance,
    Notification,
    NotificationDisplayType,
    NotificationExtraInformation,
    NotificationsAddAction,
)
from ubo_app.utils import secrets
from ubo_app.utils.apt import is_package_installed
from ubo_app.utils.async_ import create_task
from ubo_app.utils.input import ubo_input
from ubo_app.utils.monitor_unit import monitor_unit
from ubo_app.utils.persistent_store import register_persistent_store
from ubo_app.utils.server import send_command

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


def install_docker() -> None:
    """Install Docker."""

    async def act() -> None:
        store.dispatch(DockerSetStatusAction(status=DockerStatus.INSTALLING))
        result = await send_command(
            'docker',
            'install',
            has_output=True,
        )
        if result != 'installed':
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        title='Docker',
                        content='Failed to install',
                        display_type=NotificationDisplayType.STICKY,
                        color=DANGER_COLOR,
                        icon='󰜺',
                        chime=Chime.FAILURE,
                    ),
                ),
            )
        await check_docker()

    create_task(act())


def run_docker() -> None:
    """Install Docker."""

    async def act() -> None:
        await send_command('docker', 'start')
        store.dispatch(DockerSetStatusAction(status=DockerStatus.UNKNOWN))

    create_task(act())


def stop_docker() -> None:
    """Install Docker."""

    async def act() -> None:
        await send_command('docker', 'stop')
        store.dispatch(DockerSetStatusAction(status=DockerStatus.UNKNOWN))

    create_task(act())


async def check_docker() -> None:
    """Check if Docker is installed."""
    from image_ import update_container

    is_installed = await is_package_installed('docker')

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
        store.dispatch(DockerSetStatusAction(status=DockerStatus.RUNNING))
    elif is_installed:
        store.dispatch(DockerSetStatusAction(status=DockerStatus.NOT_RUNNING))
    else:
        store.dispatch(DockerSetStatusAction(status=DockerStatus.NOT_INSTALLED))


@store.autorun(lambda state: state.docker.service.status)
def setup_menu(status: DockerStatus) -> HeadedMenu:
    """Get the menu items for the Docker service."""
    title = 'Setup Docker'
    return {
        DockerStatus.UNKNOWN: HeadedMenu(
            title=title,
            heading='Checking',
            sub_heading='Checking Docker service status',
            items=[],
            placeholder='',
        ),
        DockerStatus.NOT_INSTALLED: HeadedMenu(
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
        ),
        DockerStatus.INSTALLING: HeadedMenu(
            title=title,
            heading='Installing...',
            sub_heading='Docker is being installed',
            items=[],
            placeholder='',
        ),
        DockerStatus.NOT_RUNNING: HeadedMenu(
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
        ),
        DockerStatus.RUNNING: HeadedMenu(
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
        ),
        DockerStatus.ERROR: HeadedMenu(
            title=title,
            heading='Docker Error',
            sub_heading='Please check the logs for more information',
            items=[],
            placeholder='',
        ),
    }[status]


def setup_menu_action() -> Callable[[], HeadedMenu]:
    """Get the menu items for the Docker service."""
    create_task(check_docker())
    return setup_menu


def input_credentials() -> None:
    """Input the Docker credentials."""

    async def act() -> None:
        try:
            credentials = (
                await ubo_input(
                    prompt='Enter Docker Credentials',
                    extra_information=NotificationExtraInformation(
                        text="""To generate your QR code for login, format your \
details by separating your service, username, and password with the pipe symbol. For \
example, format it as "docker.io|johndoe|password" and then convert this text into a \
QR code. If you omit the service name, "docker.io" will automatically be used as the \
default.""",
                        piper_text="""To generate your QR code for login, format your \
details by separating your service, username, and password with the pipe symbol. For \
example, format it as docker.ay o pipe johndoe pipe password and then convert this \
text into a QR code. If you omit the service name, docker.ay o will automatically be \
used as the default.""",
                        picovoice_text="""To generate your {QR|K Y UW AA R} code for \
login, format your details by separating your service, username, and password with the \
pipe symbol. For example, format it as "docker {.|D AA T} io {.|P AY P} johndoe \
{.|P AY P} password" and then convert this text into a {QR|K Y UW AA R} code. If you \
omit the service name, "docker {.|D AA T} io" will automatically be used as the \
default.""",
                    ),
                    pattern=r'^(?P<Service>[^|]*)\|(?P<Username>[^|]*)\|(?P<Password>[^|]*)$|'
                    r'(?P<Username_>^[^|]*)|(?P<Password_>[^|]*)$',
                    fields=[
                        InputFieldDescription(
                            name='Service',
                            label='Service',
                            type=InputFieldType.TEXT,
                            description='The service name',
                            default='docker.io',
                            required=False,
                        ),
                        InputFieldDescription(
                            name='Username',
                            label='Username',
                            type=InputFieldType.TEXT,
                            required=True,
                        ),
                        InputFieldDescription(
                            name='Password',
                            label='Password',
                            type=InputFieldType.PASSWORD,
                            required=True,
                        ),
                    ],
                )
            )[1]
            if not credentials:
                return
            username = credentials.get('Username', credentials.get('Username_', ''))
            password = credentials.get('Password', credentials.get('Password_', ''))
            registry = credentials.get('Service', 'docker.io')
            username = cast(str, username).strip()
            password = cast(str, password).strip()
            registry = cast(str, registry).strip()
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
            store.dispatch(
                DockerStoreUsernameAction(registry=registry, username=username),
            )
        except asyncio.CancelledError:
            pass
        except docker.errors.APIError as exception:
            explanation = exception.explanation or (
                exception.response.content.decode('utf8') if exception.response else ''
            )
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        title='Docker Credentials Error',
                        content='Invalid credentials',
                        extra_information=NotificationExtraInformation(
                            text=explanation,
                        ),
                        importance=Importance.HIGH,
                    ),
                ),
            )

    create_task(act())


def clear_credentials(registry: str) -> None:
    """Clear an entry in docker credentials."""
    secrets.clear_secret(DOCKER_CREDENTIALS_TEMPLATE.format(registry))
    store.dispatch(DockerRemoveUsernameAction(registry=registry))


@store.autorun(lambda state: state.docker.service.usernames)
def registries_menu_items(usernames: dict[str, str]) -> Sequence[Item]:
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


def _register_image_app_entry(event: DockerImageRegisterAppEvent) -> None:
    image = IMAGES[event.image]
    store.dispatch(
        RegisterRegularAppAction(
            menu_item=ActionItem(
                label=image.label,
                icon=image.icon,
                action=IMAGE_MENUS[image.id],
            ),
            key=image.id,
        ),
    )


def init_service() -> None:
    """Initialize the service."""
    register_persistent_store(
        'docker_usernames',
        lambda state: state.docker.service.usernames,
    )
    store.dispatch(
        RegisterSettingAppAction(
            priority=1,
            category=SettingsCategory.DOCKER,
            menu_item=ActionItem(
                label='Service',
                icon='',
                action=setup_menu_action,
            ),
            key='service',
        ),
    )
    store.dispatch(
        RegisterSettingAppAction(
            category=SettingsCategory.DOCKER,
            menu_item=SubMenuItem(
                label='Registries',
                icon='󱥉',
                sub_menu=HeadedMenu(
                    title='󱥉Docker Registries',
                    heading='󰡨 Docker',
                    sub_heading='Log in to a registry:',
                    items=registries_menu_items,
                ),
            ),
            key='registries',
        ),
    )

    store.subscribe_event(DockerImageRegisterAppEvent, _register_image_app_entry)

    create_task(
        monitor_unit(
            'docker.socket',
            lambda status: store.dispatch(
                DockerSetStatusAction(
                    status=DockerStatus.RUNNING
                    if status in ('active', 'activating', 'reloading')
                    else DockerStatus.NOT_RUNNING,
                ),
            ),
        ),
    )
