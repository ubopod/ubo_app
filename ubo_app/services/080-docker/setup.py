"""Setup the service."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import math
import re
import uuid
from io import BytesIO
from typing import TYPE_CHECKING

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
from docker_images import IMAGES, ContainerEntry
from menus import docker_item_menu, setup_docker_image_dynamic_menu
from reducer import image_reducer, reducer_id
from redux import CombineReducerRegisterAction

from ubo_app.colors import DANGER_COLOR, SUCCESS_COLOR, WARNING_COLOR
from ubo_app.constants import DOCKER_CREDENTIALS_TEMPLATE_SECRET_ID
from ubo_app.logger import logger
from ubo_app.store.core.types import (
    MenuItemData,
    RegisterRegularAppAction,
    RegisterSettingAppAction,
    SettingsCategory,
    UpdateDynamicMenuAction,
)
from ubo_app.store.core.view_registry import (
    register_apps_menu_title,
    register_path_menu_matcher,
)
from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    QRCodeInputDescription,
    WebUIInputDescription,
)
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
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.utils import secrets
from ubo_app.utils.apt import is_package_installed
from ubo_app.utils.async_ import create_task
from ubo_app.utils.input import ubo_input
from ubo_app.utils.monitor_unit import monitor_unit
from ubo_app.utils.persistent_store import register_persistent_store
from ubo_app.utils.server import send_command

# Dynamic menu IDs for dumb UI architecture
DOCKER_SETUP_MENU_ID = 'docker:setup'
DOCKER_REGISTRIES_MENU_ID = 'docker:registries'


def _docker_path_matcher(path: tuple[str, ...]) -> str | None:
    """Match Docker navigation paths to dynamic menu IDs.

    Args:
        path: The navigation path tuple.

    Returns:
        The dynamic menu ID if this is a Docker path, None otherwise.

    """
    # Match Docker app paths: (..., 'docker:<image_id>', [sub_key, ...])
    # Find the docker image element in the path
    for i, element in enumerate(path):
        if ':' in element:
            prefix, image_id = element.split(':', 1)
            if prefix == 'docker' and image_id and image_id not in (
                'service',
                'registries',
            ):
                menu_id = f'docker:image:{image_id}'
                # Append any nested keys (e.g., 'ports')
                for nested_key in path[i + 1 :]:
                    menu_id = f'{menu_id}:{nested_key}'
                return menu_id

    # Match Docker settings paths
    if len(path) == 4:  # noqa: PLR2004
        service_key = path[3]
        if service_key == 'docker:service':
            return DOCKER_SETUP_MENU_ID
        if service_key == 'docker:registries':
            return DOCKER_REGISTRIES_MENU_ID

    return None

if TYPE_CHECKING:
    from ubo_app.utils.types import Subscriptions


async def install_docker() -> None:
    """Install docker."""
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id='docker_install',
                title='Docker',
                content='Installing ...',
                display_type=NotificationDisplayType.STICKY,
                color=WARNING_COLOR,
                icon='󱀞',
                show_dismiss_action=False,
                progress=math.nan,
            ),
        ),
    )
    result = await send_command(
        'docker',
        'install',
        has_output=True,
    )
    if result == 'installed':
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id='docker_install',
                    title='Docker',
                    content='Installed successfully',
                    display_type=NotificationDisplayType.FLASH,
                    color=SUCCESS_COLOR,
                    icon='󰄬',
                    chime=Chime.DONE,
                ),
            ),
        )
    else:
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id='docker_install',
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


async def start_docker() -> None:
    """Start docker service."""
    await send_command('docker', 'start')


async def stop_docker() -> None:
    """Stop docker service."""
    await send_command('docker', 'stop')


async def sync_docker_containers() -> None:
    """Sync container states from Docker daemon."""
    from docker_container import update_container

    with contextlib.suppress(Exception):
        docker_client = docker.from_env()
        if not docker_client.ping():
            docker_client.close()
            return

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


async def check_docker() -> None:
    """Check if Docker is installed and set status."""
    is_installed = await is_package_installed('docker')

    is_running = False
    with contextlib.suppress(Exception):
        docker_client = docker.from_env()
        is_running = docker_client.ping()
        docker_client.close()

    if is_running:
        store.dispatch(DockerSetStatusAction(status=DockerStatus.RUNNING))
        await sync_docker_containers()
    elif is_installed:
        store.dispatch(DockerSetStatusAction(status=DockerStatus.NOT_RUNNING))
    else:
        store.dispatch(DockerSetStatusAction(status=DockerStatus.NOT_INSTALLED))


# Menu data for each Docker status (dumb UI architecture)
_DOCKER_STATUS_MENU_DATA: dict[DockerStatus, dict[str, object]] = {
    DockerStatus.UNKNOWN: {
        'title': 'Setup Docker',
        'heading': 'Checking',
        'sub_heading': 'Checking Docker service status',
        'items': (),
        'placeholder': 'Checking Docker service status...',
    },
    DockerStatus.NOT_INSTALLED: {
        'title': 'Setup Docker',
        'heading': 'Docker is not Installed',
        'sub_heading': 'Install it to enjoy the power of Docker on your Ubo pod',
        'items': (
            MenuItemData(
                key='docker:install',
                label='Install Docker',
                icon='󰶮',
                action_id='docker:install',
            ),
        ),
        'placeholder': '',
    },
    DockerStatus.INSTALLING: {
        'title': 'Setup Docker',
        'heading': 'Installing...',
        'sub_heading': 'This may take a few minutes',
        'items': (),
        'placeholder': 'Docker is being installed...',
    },
    DockerStatus.NOT_RUNNING: {
        'title': 'Setup Docker',
        'heading': 'Docker is not Running',
        'sub_heading': 'Start the Docker service',
        'items': (
            MenuItemData(
                key='docker:start',
                label='Start Docker',
                icon='󰐊',
                action_id='docker:start',
            ),
        ),
        'placeholder': '',
    },
    DockerStatus.RUNNING: {
        'title': 'Setup Docker',
        'heading': 'Docker is Running',
        'sub_heading': 'Docker service is active',
        'items': (
            MenuItemData(
                key='docker:stop',
                label='Stop Docker',
                icon='󰓛',
                action_id='docker:stop',
            ),
        ),
        'placeholder': '',
    },
    DockerStatus.ERROR: {
        'title': 'Setup Docker',
        'heading': 'Docker Error',
        'sub_heading': 'Check logs for details',
        'items': (),
        'placeholder': 'Docker Error - check logs',
    },
}


def _register_docker_action_handlers() -> None:
    """Register action handlers for Docker setup menu items."""
    from ubo_app.store.core.action_registry import (
        get_registered_actions,
        register_action,
    )

    # Only register once
    if 'docker:install' in get_registered_actions():
        return

    def _install_docker() -> None:
        store.dispatch(DockerInstallAction())

    def _start_docker() -> None:
        store.dispatch(DockerStartAction())

    def _stop_docker() -> None:
        store.dispatch(DockerStopAction())

    register_action('docker:install', _install_docker)
    register_action('docker:start', _start_docker)
    register_action('docker:stop', _stop_docker)


@store.autorun(lambda state: state.docker.service.status)
def update_docker_setup_dynamic_menu(status: DockerStatus) -> None:
    """Update the dynamic menu for Docker setup (dumb UI architecture)."""
    _register_docker_action_handlers()

    default_data = _DOCKER_STATUS_MENU_DATA[DockerStatus.UNKNOWN]
    menu_data = _DOCKER_STATUS_MENU_DATA.get(status, default_data)

    logger.debug('[Docker Service] Updating setup dynamic menu: status=%s', status)

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=DOCKER_SETUP_MENU_ID,
            title=str(menu_data['title']),
            heading=str(menu_data.get('heading', '')),
            sub_heading=str(menu_data.get('sub_heading', '')),
            items=menu_data['items'],  # type: ignore[arg-type]
            placeholder=str(menu_data['placeholder']),
        ),
    )


def input_credentials() -> None:
    """Input the Docker credentials."""

    async def act() -> None:
        try:
            credentials = (
                await ubo_input(
                    prompt='Enter Docker Credentials',
                    descriptions=[
                        QRCodeInputDescription(
                            instructions=ReadableInformation(
                                text="""To generate your QR code for login, format \
your details by separating your service, username, and password with the pipe symbol. \
For example, format it as "docker.io|johndoe|password" and then convert this text into \
a QR code. If you omit the service name, "docker.io" will automatically be used as the \
default.""",
                                piper_text="""To generate your QR code for login, \
format your details by separating your service, username, and password with the pipe \
symbol. For example, format it as docker.ay o pipe johndoe pipe password and then \
convert this text into a QR code. If you omit the service name, docker.ay o will \
automatically be used as the default.""",
                                picovoice_text="""To generate your {QR|K Y UW AA R} \
code for login, format your details by separating your service, username, and password \
with the pipe symbol. For example, format it as "docker {.|D AA T} io {.|P AY P} \
johndoe {.|P AY P} password" and then convert this text into a {QR|K Y UW AA R} code. \
If you omit the service name, "docker {.|D AA T} io" will automatically be used as the \
default.""",
                            ),
                            pattern=r'^(?P<Service>[^|]*)\|(?P<Username>[^|]*)\|(?P<Password>[^|]*)$|'
                            r'(?P<Username_>^[^|]*)|(?P<Password_>[^|]*)$',
                        ),
                        WebUIInputDescription(
                            fields=[
                                InputFieldDescription(
                                    name='Service',
                                    label='Service',
                                    type=InputFieldType.TEXT,
                                    description='The service name',
                                    default_value='docker.io',
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
                        ),
                    ],
                )
            )[1]
            if not credentials:
                return
            username = (
                credentials.data.get(
                    'Username',
                    credentials.data.get('Username_', ''),
                )
                or ''
            )
            password = (
                credentials.data.get(
                    'Password',
                    credentials.data.get('Password_', ''),
                )
                or ''
            )
            registry = credentials.data.get('Service', 'docker.io') or ''
            username = username.strip()
            password = password.strip()
            registry = registry.strip()
            docker_client = docker.from_env()
            docker_client.login(
                username=username,
                password=password,
                registry=registry,
            )
            secrets.write_secret(
                key=DOCKER_CREDENTIALS_TEMPLATE_SECRET_ID.format(registry),
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
            raise

    create_task(act())


def _slugify(text: str) -> str:
    """Convert text to a URL-friendly slug.

    Args:
        text: The text to slugify

    Returns:
        A lowercase string with spaces and special characters replaced by underscores

    """
    # Convert to lowercase
    slug = text.lower()
    # Replace spaces and special characters with underscores
    slug = re.sub(r'[^a-z0-9]+', '_', slug)
    # Remove leading/trailing underscores
    slug = slug.strip('_')
    # Collapse multiple underscores
    slug = re.sub(r'_+', '_', slug)
    return slug or 'composition'


def input_docker_composition() -> None:
    """Input the Docker composition."""

    async def act() -> None:
        with contextlib.suppress(asyncio.CancelledError):
            _, result = await ubo_input(
                prompt='Import Docker Composition',
                descriptions=[
                    WebUIInputDescription(
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
                                description='This will be saved as the '
                                'docker-compose.yml file',
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
                                description='Instructions on how to use this '
                                'composition',
                                required=False,
                            ),
                            InputFieldDescription(
                                name='content',
                                label='Directory Content',
                                type=InputFieldType.FILE,
                                description='The content of the directory in any of '
                                'these formats .tar.gz, .tar.bz2, .tar.xz, or .zip',
                                required=False,
                            ),
                        ],
                    ),
                ],
            )

            data = dict(result.data)

            if not result or not data['yaml-config'] or not data['label']:
                return

            # Generate a user-friendly ID: slugified_label_uuid
            label_slug = _slugify(data['label'])
            id = f'{label_slug}_{uuid.uuid4().hex}'
            composition_path = COMPOSITIONS_PATH / id
            composition_path.mkdir(exist_ok=True, parents=True)
            with (composition_path / 'docker-compose.yml').open('w') as file:
                file.write(data['yaml-config'])
            with (composition_path / 'metadata.json').open('w') as file:
                data.pop('yaml-config')
                file.write(json.dumps(data))

            directory_content = result.files.pop('content', None)
            # uncompress content
            if directory_content:
                header = directory_content[:6]
                directory_content_io = BytesIO(directory_content)

                if header.startswith(b'PK'):
                    import zipfile

                    with zipfile.ZipFile(directory_content_io) as zip_file:
                        zip_file.extractall(path=composition_path)
                if header.startswith((b'\x1f\x8b', b'BZh', b'\xfd7zXZ')):
                    import tarfile

                    with tarfile.open(fileobj=directory_content_io) as tar_file:
                        tar_file.extractall(path=composition_path)  # noqa: S202

            IMAGES[id] = ContainerEntry(
                id=id,
                label=data['label'],
                icon=data.get('icon', '󰣆'),
                path=str(composition_path),
                registry='docker.io',
                is_composition=True,
            )

            store.dispatch(
                CombineReducerRegisterAction(
                    combine_reducers_id=reducer_id,
                    key=id,
                    reducer=image_reducer,
                    payload=data,
                ),
            )

    create_task(act())


def clear_credentials(registry: str) -> None:
    """Clear an entry in docker credentials."""
    secrets.clear_secret(DOCKER_CREDENTIALS_TEMPLATE_SECRET_ID.format(registry))
    store.dispatch(DockerRemoveUsernameAction(registry=registry))


_registries_action_ids: list[str] = []


@store.autorun(lambda state: state.docker.service.usernames)
def registries_menu_items(usernames: dict[str, str]) -> None:
    """Update the dynamic menu for Docker registries."""
    from ubo_app.store.core.action_registry import register_action, unregister_action

    # Unregister old action handlers from previous autorun invocation
    for action_id in _registries_action_ids:
        unregister_action(action_id)
    _registries_action_ids.clear()

    # Register action for "Add Registry"
    add_registry_action_id = 'docker:add-registry'
    unregister_action(add_registry_action_id)
    register_action(add_registry_action_id, input_credentials)
    _registries_action_ids.append(add_registry_action_id)

    items: list[MenuItemData] = [
        MenuItemData(
            key='docker:add-registry',
            label='Add Registry',
            icon='󰌉',
            action_id=add_registry_action_id,
        ),
    ]

    if usernames:
        # Build registry items and register their actions
        registry_items: list[MenuItemData] = []
        for registry in usernames:
            action_id = f'docker:clear-credentials:{registry}'
            unregister_action(action_id)
            register_action(
                action_id,
                functools.partial(clear_credentials, registry),
            )
            _registries_action_ids.append(action_id)
            registry_items.append(
                MenuItemData(
                    key=f'docker:registry:{registry}',
                    label=registry,
                    icon='󰌊',
                    background_color=DANGER_COLOR,
                    action_id=action_id,
                ),
            )

        # Register action to open the registries sub-menu
        open_registries_action_id = 'docker:open-registries'
        unregister_action(open_registries_action_id)
        register_action(
            open_registries_action_id,
            lambda: store.dispatch(
                UpdateDynamicMenuAction(
                    menu_id='docker:registries:list',
                    title='󱕴Registries',
                    heading='Logged in Registries',
                    sub_heading='Log out of any registry by selecting it',
                    items=tuple(registry_items),
                ),
            ),
        )
        _registries_action_ids.append(open_registries_action_id)

        items.append(
            MenuItemData(
                key='docker:registries-list',
                label='Registries',
                icon='󱕴',
                action_id=open_registries_action_id,
            ),
        )

        # Also dispatch the child menu so it's ready if already navigated
        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id='docker:registries:list',
                title='󱕴Registries',
                heading='Logged in Registries',
                sub_heading='Log out of any registry by selecting it',
                items=tuple(registry_items),
            ),
        )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=DOCKER_REGISTRIES_MENU_ID,
            title='Docker Registries',
            heading='󰡨 Docker',
            sub_heading='Log in to a registry:',
            items=tuple(items),
        ),
    )


def _register_composition_entry(image_id: str) -> None:
    """Register a composition in the main menu."""
    if image_id not in IMAGES:
        logger.error('Composition not found in IMAGES', extra={'image': image_id})
        return

    image_entry = IMAGES[image_id]
    action_id = f'docker:open:{image_id}'
    from contextlib import suppress

    from ubo_app.store.core.action_registry import register_action

    with suppress(ValueError):
        register_action(action_id, functools.partial(docker_item_menu, image_id))
    store.dispatch(
        RegisterRegularAppAction(
            label=image_entry.label,
            icon=image_entry.icon or '󰣆',
            action_id=action_id,
            key=image_id,
        ),
    )
    setup_docker_image_dynamic_menu(image_id)


def _register_container_entry(image_id: str) -> None:
    """Register a regular container in the main menu."""
    action_id = f'docker:open:{image_id}'
    from contextlib import suppress

    from ubo_app.store.core.action_registry import register_action

    with suppress(ValueError):
        register_action(action_id, functools.partial(docker_item_menu, image_id))
    store.dispatch(
        RegisterRegularAppAction(
            label=IMAGES[image_id].label,
            icon=IMAGES[image_id].icon,
            action_id=action_id,
            key=image_id,
        ),
    )
    setup_docker_image_dynamic_menu(image_id)


def _register_image_app_entry(event: DockerImageRegisterAppEvent) -> None:
    """Register the image as an entry in the main menu."""
    image_id = event.image
    if image_id in IMAGES and IMAGES[image_id].is_composition:
        _register_composition_entry(image_id)
    else:
        _register_container_entry(image_id)


def _load_images() -> None:
    # First, populate IMAGES with dynamically imported compositions from disk
    for item in (
        COMPOSITIONS_PATH.iterdir() if COMPOSITIONS_PATH.is_dir() else []
    ):
        if not item.is_dir():
            continue
        if item.stem in IMAGES:
            continue
        if not (item / 'metadata.json').exists():
            continue

        try:
            metadata = json.load((item / 'metadata.json').open())
            IMAGES[item.stem] = ContainerEntry(
                id=item.stem,
                label=metadata['label'],
                icon=metadata.get('icon', '󰣆'),
                path=str(item),
                registry='docker.io',
                is_composition=True,
            )
        except Exception:
            logger.exception(
                'Failed to load composition',
                extra={'composition': item.stem},
            )

    # Now register all images (both predefined and dynamically imported) with Redux
    store.dispatch(
        [
            CombineReducerRegisterAction(
                combine_reducers_id=reducer_id,
                key=image_id,
                reducer=image_reducer,
                payload=(
                    json.load(
                        (COMPOSITIONS_PATH / image_id / 'metadata.json').open(),
                    )
                    if IMAGES[image_id].is_composition
                    and (COMPOSITIONS_PATH / image_id / 'metadata.json').exists()
                    else {'label': IMAGES[image_id].label}
                ),
            )
            for image_id in IMAGES
        ],
    )


async def init_service() -> Subscriptions:
    """Initialize the service."""
    # Register apps menu title
    unregister_title = register_apps_menu_title('󰀻Docker Apps')

    # Register path matcher for Docker navigation (apps and settings)
    unregister_path_matcher = register_path_menu_matcher(
        'docker:paths',
        _docker_path_matcher,
    )

    register_persistent_store(
        'docker_usernames',
        lambda state: state.docker.service.usernames,
    )

    from ubo_app.store.core.action_registry import register_action

    register_action('docker:import_composition', input_docker_composition)
    store.dispatch(
        RegisterRegularAppAction(
            priority=1,
            label='Import YAML file',
            icon='󰋺',
            background_color=WARNING_COLOR,
            action_id='docker:import_composition',
            key='_import',
        ),
        RegisterSettingAppAction(
            priority=1,
            category=SettingsCategory.DOCKER,
            label='Service',
            icon='',
            key='service',
        ),
        RegisterSettingAppAction(
            priority=2,
            category=SettingsCategory.DOCKER,
            label='Registries',
            icon='󱥉',
            key='registries',
        ),
    )

    subscriptions = [
        store.subscribe_event(
            DockerImageRegisterAppEvent,
            _register_image_app_entry,
        ),
        store.subscribe_event(DockerInstallEvent, install_docker),
        store.subscribe_event(DockerStartEvent, start_docker),
        store.subscribe_event(DockerStopEvent, stop_docker),
        store.subscribe_event(DockerImageFetchCompositionEvent, pull_composition),
        store.subscribe_event(DockerImageFetchEvent, fetch_image),
        store.subscribe_event(DockerImageRemoveCompositionEvent, remove_composition),
        store.subscribe_event(DockerImageRemoveEvent, remove_image),
        store.subscribe_event(DockerImageRunCompositionEvent, run_composition),
        store.subscribe_event(DockerImageRunContainerEvent, run_container),
        store.subscribe_event(DockerImageStopCompositionEvent, stop_composition),
        store.subscribe_event(DockerImageStopContainerEvent, stop_container),
        store.subscribe_event(DockerImageReleaseCompositionEvent, release_composition),
        store.subscribe_event(DockerImageRemoveContainerEvent, remove_container),
    ]

    async def handle_docker_status(status: str) -> None:
        """Handle Docker status changes from systemd."""
        is_running = status in ('active', 'activating', 'reloading')
        store.dispatch(
            DockerSetStatusAction(
                status=DockerStatus.RUNNING if is_running else DockerStatus.NOT_RUNNING,
            ),
        )
        if is_running:
            await sync_docker_containers()

    def docker_status_callback(status: str) -> None:
        """Run task for Docker status changes."""
        create_task(handle_docker_status(status))

    _load_images()
    await check_docker()
    create_task(
        monitor_unit(
            'docker.socket',
            docker_status_callback,
        ),
    )

    return [
        *subscriptions,
        unregister_title,
        unregister_path_matcher,
    ]
