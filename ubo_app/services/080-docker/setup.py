"""Setup the service."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import uuid
from typing import TYPE_CHECKING, cast

import docker
import docker.errors
from docker.models.containers import Container
from docker.models.images import Image
from docker_composition import (
    COMPOSITIONS_PATH,
    pull_composition,
    release_composition,
    remove_composition,
    run_composition,
    stop_composition,
)
from docker_container import remove_container, run_container, stop_container
from docker_image import fetch_image, remove_image
from docker_images import IMAGES
from menus import docker_item_menu
from reducer import image_reducer, reducer_id
from redux import CombineReducerRegisterAction
from ubo_gui.constants import DANGER_COLOR, WARNING_COLOR
from ubo_gui.menu.types import ActionItem, HeadedMenu, Item, SubMenuItem

from ubo_app.constants import DOCKER_CREDENTIALS_TEMPLATE
from ubo_app.logger import logger
from ubo_app.store.core.types import (
    RegisterRegularAppAction,
    RegisterSettingAppAction,
    SettingsCategory,
)
from ubo_app.store.dispatch_action import DispatchItem
from ubo_app.store.input.types import InputFieldDescription, InputFieldType, InputMethod
from ubo_app.store.main import store
from ubo_app.store.services.docker import (
    DockerImageFetchCompositionEvent,
    DockerImageFetchEvent,
    DockerImageRegisterAppEvent,
    DockerImageReleaseCompositionEvent,
    DockerImageRemoveCompositionEvent,
    DockerImageRemoveContainerEvent,
    DockerImageRemoveEvent,
    DockerImageRunCompositionEvent,
    DockerImageRunContainerEvent,
    DockerImageStopCompositionEvent,
    DockerImageStopContainerEvent,
    DockerInstallAction,
    DockerInstallEvent,
    DockerLoadImagesEvent,
    DockerRemoveUsernameAction,
    DockerSetStatusAction,
    DockerStartAction,
    DockerStartEvent,
    DockerStatus,
    DockerStopAction,
    DockerStopEvent,
    DockerStoreUsernameAction,
)
from ubo_app.store.services.notifications import (
    Chime,
    Importance,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.voice import ReadableInformation
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
    """Install docker."""

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


def start_docker() -> None:
    """Start docker service."""

    async def act() -> None:
        await send_command('docker', 'start')
        store.dispatch(DockerSetStatusAction(status=DockerStatus.UNKNOWN))

    create_task(act())


def stop_docker() -> None:
    """Stop docker service."""

    async def act() -> None:
        await send_command('docker', 'stop')
        store.dispatch(DockerSetStatusAction(status=DockerStatus.UNKNOWN))

    create_task(act())


async def check_docker() -> None:
    """Check if Docker is installed."""
    from docker_container import update_container

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
                        update_container(image_id=image_id, container=container)

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
                DispatchItem(
                    label='Install Docker',
                    icon='󰶮',
                    store_action=DockerInstallAction(),
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
                DispatchItem(
                    label='Start Docker',
                    icon='󰐊',
                    store_action=DockerStartAction(),
                ),
            ],
        ),
        DockerStatus.RUNNING: HeadedMenu(
            title=title,
            heading='Docker is Running',
            sub_heading='Enjoy the power of Docker on your Ubo pod',
            items=[
                DispatchItem(
                    label='Stop Docker',
                    icon='󰓛',
                    store_action=DockerStopAction(),
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
                    qr_code_generation_instructions=ReadableInformation(
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
            username = credentials.data.get(
                'Username',
                credentials.data.get('Username_', ''),
            )
            password = credentials.data.get(
                'Password',
                credentials.data.get('Password_', ''),
            )
            registry = credentials.data.get('Service', 'docker.io')
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
                        extra_information=ReadableInformation(
                            text=explanation,
                        ),
                        importance=Importance.HIGH,
                    ),
                ),
            )

    create_task(act())


def input_docker_composition() -> None:
    """Input the Docker credentials."""

    async def act() -> None:
        with contextlib.suppress(asyncio.CancelledError):
            _, result = await ubo_input(
                input_methods=InputMethod.WEB_DASHBOARD,
                prompt='Import Docker Composition',
                fields=[
                    InputFieldDescription(
                        name='label',
                        label='Label',
                        type=InputFieldType.TEXT,
                        description='The label of this composition',
                        required=True,
                    ),
                    InputFieldDescription(
                        name='yaml-config',
                        label='Compose YAML',
                        type=InputFieldType.LONG,
                        description='This will be saved as the docker-compose.yml file',
                        required=True,
                    ),
                    InputFieldDescription(
                        name='icon',
                        label='Icon',
                        type=InputFieldType.TEXT,
                        description="""<a \
href="https://www.nerdfonts.com/cheat-sheet" target="_blank">Nerd Fonts</a> are \
supported""",
                        required=False,
                    ),
                    InputFieldDescription(
                        name='instructions',
                        label='Instructions',
                        type=InputFieldType.LONG,
                        description='Instructions on how to use this composition',
                        required=False,
                    ),
                    InputFieldDescription(
                        name='content',
                        label='Directory Content',
                        type=InputFieldType.FILE,
                        description='The content of the directory in any of these '
                        'formats .tar.gz, .tar.bz2, .tar.xz, or .zip',
                        required=False,
                    ),
                ],
            )

            if not result or not result.data['yaml-config'] or not result.data['label']:
                return

            id = f'composition_{uuid.uuid4().hex}'
            composition_path = COMPOSITIONS_PATH / id
            composition_path.mkdir(exist_ok=True, parents=True)
            with (composition_path / 'docker-compose.yml').open('w') as file:
                file.write(result.data['yaml-config'])
            with (composition_path / 'metadata.json').open('w') as file:
                result.data.pop('yaml-config')
                file.write(json.dumps(result.data))

            directory_content = result.files.pop('content', None)
            # uncompress content
            if directory_content:
                header = directory_content.read(6)
                directory_content.seek(0)

                if header.startswith(b'PK'):
                    directory_content.seek(0)
                    import zipfile

                    with zipfile.ZipFile(directory_content) as zip_file:
                        zip_file.extractall(path=composition_path)
                if header.startswith((b'\x1f\x8b', b'BZh', b'\xfd7zXZ')):
                    import tarfile

                    with tarfile.open(fileobj=directory_content) as tar_file:
                        tar_file.extractall(path=composition_path)  # noqa: S202

            store.dispatch(
                CombineReducerRegisterAction(
                    _id=reducer_id,
                    key=id,
                    reducer=image_reducer,
                    payload=result.data,
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
    if event.image in IMAGES:
        image = IMAGES[event.image]
        store.dispatch(
            RegisterRegularAppAction(
                menu_item=ActionItem(
                    label=image.label,
                    icon=image.icon,
                    action=functools.partial(docker_item_menu, image.id),
                ),
                key=image.id,
            ),
        )
    else:
        path = COMPOSITIONS_PATH / event.image
        if not path.exists():
            logger.error('Composition not found', extra={'image': event.image})
            return
        metadata = json.load((path / 'metadata.json').open())
        store.dispatch(
            RegisterRegularAppAction(
                menu_item=ActionItem(
                    label=metadata['label'],
                    icon=metadata['icon'] or '󰣆',
                    action=functools.partial(docker_item_menu, event.image),
                ),
                key=event.image,
            ),
        )


def _load_images() -> None:
    store.dispatch(
        [
            CombineReducerRegisterAction(
                _id=reducer_id,
                key=image_id,
                reducer=image_reducer,
                payload={'label': IMAGES[image_id].label},
            )
            for image_id in IMAGES
        ],
        [
            CombineReducerRegisterAction(
                _id=reducer_id,
                key=item.stem,
                reducer=image_reducer,
                payload=json.load((item / 'metadata.json').open()),
            )
            for item in (
                COMPOSITIONS_PATH.iterdir() if COMPOSITIONS_PATH.is_dir() else []
            )
            if item.stem.startswith('composition_')
        ],
    )


def init_service() -> None:
    """Initialize the service."""
    register_persistent_store(
        'docker_usernames',
        lambda state: state.docker.service.usernames,
    )
    store.dispatch(
        RegisterRegularAppAction(
            priority=1,
            menu_item=ActionItem(
                label='Import YAML file',
                icon='󰋺',
                background_color=WARNING_COLOR,
                color='black',
                action=input_docker_composition,
            ),
            key='_import',
        ),
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
        RegisterSettingAppAction(
            priority=2,
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

    store.subscribe_event(DockerLoadImagesEvent, _load_images)
    store.subscribe_event(
        DockerImageRegisterAppEvent,
        _register_image_app_entry,
    )

    store.subscribe_event(DockerInstallEvent, install_docker)
    store.subscribe_event(DockerStartEvent, start_docker)
    store.subscribe_event(DockerStopEvent, stop_docker)

    store.subscribe_event(DockerImageFetchCompositionEvent, pull_composition)
    store.subscribe_event(DockerImageFetchEvent, fetch_image)
    store.subscribe_event(DockerImageRemoveCompositionEvent, remove_composition)
    store.subscribe_event(DockerImageRemoveEvent, remove_image)
    store.subscribe_event(DockerImageRunCompositionEvent, run_composition)
    store.subscribe_event(DockerImageRunContainerEvent, run_container)
    store.subscribe_event(DockerImageStopCompositionEvent, stop_composition)
    store.subscribe_event(DockerImageStopContainerEvent, stop_container)
    store.subscribe_event(DockerImageReleaseCompositionEvent, release_composition)
    store.subscribe_event(DockerImageRemoveContainerEvent, remove_container)

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
