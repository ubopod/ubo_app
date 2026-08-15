"""Setup the service."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import math
import re
import socket
import uuid
from io import BytesIO
from typing import TYPE_CHECKING, TypedDict

import docker
import docker.errors
from apps import IMAGES, UBO_NET, ContainerEntry
from apps.home_assistant import (
    HOME_ASSISTANT_COMPOSITION_ID,
    zigbee_adapter_went_missing,
)
from docker.models.containers import Container
from docker.models.images import Image
from docker_app import prepare_app
from docker_composition import (
    COMPOSITIONS_PATH,
    check_composition,
    pull_composition,
    release_composition,
    remove_composition,
    run_composition,
    stop_composition,
)
from docker_container import (
    find_container,
    register_container_start_hook,
    remove_container,
    run_container,
    start_event_monitor,
    stop_container,
)
from docker_image import fetch_image, remove_image
from docker_logs import open_logs_image, stop_log_tail, sync_log_tail
from grpc_lan import (
    GrpcToggle,
    classify_grpc_toggle,
    should_announce_exposed,
    should_prompt_envoy,
    should_start_envoy_at_boot,
)
from menus import docker_item_menu, setup_docker_image_dynamic_menu
from reducer import image_reducer, reducer_id
from redux import CombineReducerRegisterAction

from ubo_app.colors import DANGER_COLOR, SUCCESS_COLOR, WARNING_COLOR
from ubo_app.constants import (
    DOCKER_CREDENTIALS_TEMPLATE_SECRET_ID,
    GRPC_NATIVE_PROXY_LISTEN_PORT,
)
from ubo_app.logger import logger
from ubo_app.store.core.constants import APPS_ROOT_CATEGORY
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
    DockerImageRebindEvent,
    DockerImageRegisterAppEvent,
    DockerImageReleaseCompositionEvent,
    DockerImageRemoveCompositionEvent,
    DockerImageRemoveContainerAction,
    DockerImageRemoveContainerEvent,
    DockerImageRemoveEvent,
    DockerImageRunAction,
    DockerImageRunCompositionEvent,
    DockerImageRunContainerEvent,
    DockerImageStopAction,
    DockerImageStopCompositionEvent,
    DockerImageStopContainerEvent,
    DockerInstallAction,
    DockerInstallEvent,
    DockerItemStatus,
    DockerRemoveUsernameAction,
    DockerSetStatusAction,
    DockerStartAction,
    DockerStartEvent,
    DockerState,
    DockerStatus,
    DockerStopAction,
    DockerStopEvent,
    DockerStoreUsernameAction,
    ImageState,
)
from ubo_app.store.services.notifications import (
    Chime,
    Importance,
    Notification,
    NotificationDispatchItem,
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
from ubo_app.utils.zeroconf import register_service, unregister_service

# Dynamic menu IDs for dumb UI architecture
DOCKER_SETUP_MENU_ID = 'docker:setup'
DOCKER_REGISTRIES_MENU_ID = 'docker:registries'
DEFAULT_APP_CATEGORY = 'Other'
DOCKER_APP_CATEGORY_ORDER = (
    'Home Automation',
    'Networking',
    'AI Agents',
    'AI Engines',
    'Remote Access',
    'Files',
    'Container Management',
    DEFAULT_APP_CATEGORY,
)


class DockerStatusMenuData(TypedDict):
    """Static menu data for one Docker service status."""

    title: str
    heading: str
    sub_heading: str
    items: tuple[MenuItemData, ...]
    placeholder: str


def _normalize_category(category: str | None) -> str:
    """Return a display-safe app category."""
    return category.strip() if category and category.strip() else DEFAULT_APP_CATEGORY


def _category_sort_key(category: str) -> tuple[int, str]:
    """Sort known app categories first, then custom categories by label."""
    try:
        return (DOCKER_APP_CATEGORY_ORDER.index(category), category.lower())
    except ValueError:
        return (len(DOCKER_APP_CATEGORY_ORDER), category.lower())


def _docker_app_category_options() -> list[str]:
    """Return existing Docker app categories for import selection."""
    categories = {
        *(entry.category for entry in IMAGES.values() if entry.category),
        *DOCKER_APP_CATEGORY_ORDER,
    }
    return sorted(
        (_normalize_category(category) for category in categories),
        key=_category_sort_key,
    )


def _resolve_category(selected: str | None, custom: str | None) -> str:
    """Resolve the selected or user-defined category from import input."""
    custom_category = custom.strip() if custom else ''
    return _normalize_category(custom_category or selected)


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
            if (
                prefix == 'docker'
                and image_id
                and image_id
                not in (
                    'service',
                    'registries',
                )
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
    from collections.abc import Sequence

    from ubo_app.store.services.ip import IpNetworkInterface
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


def ensure_ubo_net(docker_client: docker.DockerClient) -> None:
    """Idempotently create the shared `ubo_net` bridge.

    `ubo_net` is the cross-stack integration bus that Ubo-managed compositions
    attach to (declared `external: true` in their compose files), so it must
    pre-exist before any `docker compose up`. It is shared infrastructure owned
    by the docker service: created once, never auto-deleted on single-stack
    removal.
    """
    if not docker_client.networks.list(names=[UBO_NET]):
        docker_client.networks.create(UBO_NET, driver='bridge')


async def sync_docker_containers() -> None:
    """Sync container states from Docker daemon."""
    from docker_container import check_container, update_container

    with contextlib.suppress(Exception):
        docker_client = docker.from_env()
        if not docker_client.ping():
            docker_client.close()
            return

        ensure_ubo_net(docker_client)

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

    # Bootstrap event monitors for all non-composition images so we get
    # live state updates without polling. start_event_monitor is idempotent.
    #
    # Also imperatively refresh each image's status: the container scan above
    # only reflects existing *containers*, so an image that is already pulled
    # but has no container would otherwise stay at the default NOT_AVAILABLE.
    # Consumers that read the store without first opening the docker menu
    # (e.g. the assistant's Ollama setup) would then see a stale NOT_AVAILABLE
    # and offer to re-fetch an image that's already present. check_container
    # reports AVAILABLE for a present image and reconciles container state too.
    for image_id, image_description in IMAGES.items():
        if image_description.is_composition:
            # Reconcile composition *status* at boot so consumers reading the
            # store (without opening the docker menu) don't see a stale
            # NOT_AVAILABLE. Deliberately status-only: we do not re-render
            # (`prepare_app`) or recreate (`run_composition`) here, since some
            # prepare hooks fetch over the network and a blanket recreate would
            # restart unrelated running compositions on every docker-check. The
            # render-at-run hook (run_composition) keeps each compose file fresh
            # whenever it is actually (re)started.
            await check_composition(id=image_id)
            if image_id == HOME_ASSISTANT_COMPOSITION_ID:
                # HA-specific: heal a Zigbee-bricked start (see function doc).
                heal_home_assistant_zigbee()
            continue
        start_event_monitor(image_id)
        check_container(image_id=image_id)


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


_DOCKER_STATUS_MENU_DATA: dict[DockerStatus, DockerStatusMenuData] = {
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
            heading=menu_data['heading'],
            sub_heading=menu_data['sub_heading'],
            items=menu_data['items'],
            placeholder=menu_data['placeholder'],
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
                                name='category',
                                label='Category',
                                type=InputFieldType.SELECT,
                                description='Where this app appears in Apps',
                                options=_docker_app_category_options(),
                                default_value=DEFAULT_APP_CATEGORY,
                                required=False,
                            ),
                            InputFieldDescription(
                                name='new-category',
                                label='New category',
                                type=InputFieldType.TEXT,
                                description='Optional category name to create',
                                required=False,
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

            if not result:
                return

            data = dict(result.data)

            if not data.get('yaml-config') or not data.get('label'):
                return

            data['category'] = _resolve_category(
                selected=data.get('category'),
                custom=data.get('new-category'),
            )

            # Generate a user-friendly ID: slugified_label_uuid
            label_slug = _slugify(data['label'])
            id = f'{label_slug}_{uuid.uuid4().hex}'
            composition_path = COMPOSITIONS_PATH / id
            composition_path.mkdir(exist_ok=True, parents=True)
            with (composition_path / 'docker-compose.yml').open('w') as file:
                file.write(data['yaml-config'])
            with (composition_path / 'metadata.json').open('w') as file:
                data.pop('yaml-config')
                data.pop('new-category', None)
                file.write(json.dumps(data))

            content_upload_id = result.data.get('content_upload_id')
            if content_upload_id:
                from ubo_app.utils.file_upload import await_completed_upload

                directory_content = await await_completed_upload(content_upload_id)
            else:
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
                category=data['category'],
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
            app_category=image_entry.category,
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
            app_category=IMAGES[image_id].category,
        ),
    )
    setup_docker_image_dynamic_menu(image_id)
    # Idempotent; safe to call when docker is down — the monitor thread
    # cleans up after a failed connect so a later call retries.
    start_event_monitor(image_id)


def _register_image_app_entry(event: DockerImageRegisterAppEvent) -> None:
    """Register the image as an entry in the main menu."""
    image_id = event.image
    if image_id in IMAGES and IMAGES[image_id].is_composition:
        _register_composition_entry(image_id)
    else:
        _register_container_entry(image_id)


def _load_images() -> None:
    # First, populate IMAGES with dynamically imported compositions from disk
    for item in COMPOSITIONS_PATH.iterdir() if COMPOSITIONS_PATH.is_dir() else []:
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
                category=metadata.get('category', DEFAULT_APP_CATEGORY),
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


@store.with_state(lambda state: state.docker)
def handle_rebind(docker_state: DockerState, event: DockerImageRebindEvent) -> None:
    """Recreate/restart an app so a changed port binding takes effect.

    Only acts when the app is currently up. Compositions are recreated by
    ``docker compose up -d`` (which re-patches the compose ports first); a
    single container keeps its original binding until removed, so it is
    stopped, removed and re-run with the new binding.
    """
    image = event.image
    image_state = getattr(docker_state, image, None)
    if image_state is None or image_state.status not in (
        DockerItemStatus.RUNNING,
        DockerItemStatus.STARTING,
        DockerItemStatus.CREATED,
    ):
        return
    entry = IMAGES.get(image)
    if entry is None:
        return
    if entry.is_composition:
        store.dispatch(DockerImageRunAction(image=image))
    else:
        store.dispatch(
            DockerImageStopAction(image=image),
            DockerImageRemoveContainerAction(image=image),
            DockerImageRunAction(image=image),
        )


@store.with_state(
    lambda state: getattr(state.docker, HOME_ASSISTANT_COMPOSITION_ID, None),
)
def heal_home_assistant_zigbee(image_state: ImageState | None) -> None:
    """Recover HA if an unsatisfiable Zigbee `devices:` line bricked its start.

    When HA exists but isn't running (``CREATED``) and the Zigbee intent can't
    be satisfied (adapter unplugged), its create-time ``devices:`` mapping would
    hard-fail ``up`` on the Docker daemon's own ``restart: unless-stopped``
    relaunch. Re-render (dropping the absent mapping) + recreate via
    ``DockerImageRunAction`` so HA boots degraded instead of restart-looping
    unattended. Scoped to HA (the only device-bearing composition) so a normal
    user-stopped composition is left alone.
    """
    if (
        image_state is not None
        and image_state.status == DockerItemStatus.CREATED
        and zigbee_adapter_went_missing()
    ):
        store.dispatch(DockerImageRunAction(image=HOME_ASSISTANT_COMPOSITION_ID))


# =============================================================================
# gRPC LAN access (Envoy native-gRPC TCP listener) — event driven
# =============================================================================
# Source of truth is `settings.grpc_remote_access`. When on, the Envoy proxy must
# run with the native-gRPC TCP listener rendered into its config (see
# apps/envoy.py); when off, that listener must be gone.
#
# Exposure is driven by events, never by monitoring Envoy's status:
#   * the user toggling `grpc_remote_access` — apply the listener + restart Envoy
#     if it is running, otherwise prompt to download+start it;
#   * the Envoy container starting — announce reachability if gRPC access is on.
# Boot additionally *reconciles* once: `grpc_remote_access` is on by default, so a
# fresh pod has to bring Envoy up itself or the setting would expose nothing and
# the mobile clients would never discover the device. An already-running Envoy is
# left as-is (it already fronts gRPC-web and carries the persisted listener
# config); a down Envoy is started only when its image is already local, so boot
# never pulls over the network unprompted.
ENVOY_IMAGE_ID = 'envoy_grpc'
# Current `grpc_remote_access`, cached by the toggle autorun so the start hook can
# read it without re-touching the store. `None` = boot value not yet observed.
_grpc_enabled: list[bool | None] = [None]
# The persisted setting hydrates into the store during boot, which the toggle
# autorun would otherwise see as a user off→on toggle and act on (restarting
# Envoy / re-prompting). Stay inert until boot settles; flipped once, at the end
# of `init_service`, after hydration is done. Only genuine post-boot toggles act.
_grpc_toggle_ready: list[bool] = [False]
# Set while boot's reconciliation start is in flight, so the resulting `start`
# event advertises over mDNS but skips the sticky "gRPC exposed" warning — that
# warning acknowledges a user action, and would otherwise fire on every reboot.
_boot_envoy_start: list[bool] = [False]
# Whether Envoy is up, tracked from the container `start` hook. The LAN-IP
# autorun needs this and cannot call `_envoy_running` (blocking Docker I/O).
_envoy_up: list[bool] = [False]
# The address the mDNS record currently advertises, so the LAN-IP autorun only
# re-registers on a genuine change.
_advertised_ip: list[str | None] = [None]


# Virtual / non-LAN interfaces whose addresses are useless to advertise.
_LAN_EXCLUDE_PREFIXES = ('lo', 'docker', 'br-', 'veth', 'tun', 'tap', 'utun')


@store.with_state(
    lambda state: state.ip.interfaces if hasattr(state, 'ip') else None,
)
def _lan_ip(interfaces: Sequence[IpNetworkInterface] | None) -> str | None:
    """Return a likely LAN IPv4 address, preferring ethernet/wireless NICs.

    Skips loopback, Docker/bridge/veth and VPN/tunnel interfaces, and prefers
    physical ethernet (``eth*``/``en*``) and wireless (``wlan*``/``wl*``) NICs
    over anything else so the advertised address is actually reachable.
    """
    fallback: str | None = None
    for interface in interfaces or []:
        if interface.name.startswith(_LAN_EXCLUDE_PREFIXES):
            continue
        for ip in interface.ip_addresses:
            if ':' in ip or ip.startswith('127.'):
                continue
            if interface.name.startswith(('e', 'w')):
                return ip
            if fallback is None:
                fallback = ip
    return fallback


def _announce_grpc_reachable() -> None:
    """Announce that gRPC is now exposed — with the address and the risk.

    This single notification merges what used to be two (a security warning on
    toggle, then a reachability info): now that Envoy has actually started and is
    exposing the port, the user gets one sticky message carrying both the address
    and the warning, so there is only one thing to read and dismiss.
    """
    ip = _lan_ip()
    address = (
        f'{ip}:{GRPC_NATIVE_PROXY_LISTEN_PORT}'
        if ip
        else f':{GRPC_NATIVE_PROXY_LISTEN_PORT}'
    )
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id='grpc-access-exposed',
                title='gRPC Access',
                content=f'gRPC API exposed at {address}. Unauthenticated — unsafe '
                'while exposed.',
                extra_information=ReadableInformation(
                    text=f"This Ubo's gRPC control API is now reachable at "
                    f'{address} through the Envoy proxy. It is not authenticated, '
                    'so while it is exposed any device on your network could read '
                    'state or send commands. Only leave this on for a trusted '
                    'network; disable gRPC access to restrict it back to this '
                    'device only (localhost).',
                    picovoice_text='',
                    piper_text='',
                ),
                icon='󰀪',
                importance=Importance.HIGH,
                color=WARNING_COLOR,
                display_type=NotificationDisplayType.STICKY,
            ),
        ),
    )


_UBORPC_SERVICE_TYPE = '_uborpc._tcp.local.'


def _uborpc_zeroconf_name() -> str:
    """Instance name for the gRPC control API's mDNS advertisement.

    Pod hostnames are already `ubo-<id>`-prefixed by convention, so this just
    sanitizes the hostname rather than adding a second `ubo-` prefix.
    """
    name = re.sub(r'[^A-Za-z0-9-]', '-', socket.gethostname())
    return f'{name}.{_UBORPC_SERVICE_TYPE}'


async def _advertise_uborpc() -> None:
    """Advertise the gRPC control API over mDNS, if it has a LAN address.

    Silently no-ops without a LAN IP (nothing reachable to advertise) — same
    condition `_announce_grpc_reachable` already tolerates.
    """
    ip = _lan_ip()
    if ip is None:
        return
    await register_service(
        service_type=_UBORPC_SERVICE_TYPE,
        name=_uborpc_zeroconf_name(),
        address=ip,
        port=GRPC_NATIVE_PROXY_LISTEN_PORT,
    )
    _advertised_ip[0] = ip


async def _withdraw_uborpc() -> None:
    """Stop advertising the gRPC control API over mDNS."""
    _advertised_ip[0] = None
    await unregister_service(_uborpc_zeroconf_name())


def _restart_envoy_container() -> None:
    """Restart the Envoy container in place (blocking Docker I/O)."""
    client = docker.from_env()
    try:
        container = find_container(client, image_path=IMAGES[ENVOY_IMAGE_ID].path)
        if container is not None:
            # ``restart`` starts a stopped/created container too, so this both
            # applies a new config to a running Envoy and boots a stopped one.
            container.restart()
    finally:
        client.close()


async def _apply_envoy() -> None:
    """Re-render the Envoy config from the current gRPC setting and restart it.

    `prepare_app` renders `apps/envoy.py` reading the live `grpc_remote_access`,
    so the listener is included/excluded to match the just-toggled setting. The
    config is bind-mounted, so an in-place restart reloads it — no recreate. When
    gRPC access is on, the restart's `start` event is what announces reachability
    (`_on_envoy_started`), so this does not announce itself.
    """
    if not await prepare_app(IMAGES[ENVOY_IMAGE_ID]):
        logger.error('Failed to render Envoy config for gRPC LAN access')
        return
    await asyncio.to_thread(_restart_envoy_container)


def _prompt_envoy_needed() -> None:
    """Offer to download and start Envoy, which the LAN listener rides on."""
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id='grpc-access-envoy-needed',
                title='gRPC Access',
                content='The Envoy proxy is needed to expose gRPC to the LAN. '
                'Download and start it?',
                icon='󱂇',
                importance=Importance.MEDIUM,
                color=WARNING_COLOR,
                display_type=NotificationDisplayType.STICKY,
                actions=[
                    NotificationDispatchItem(
                        key='download',
                        label='Download & Start',
                        icon='󰇚',
                        # Running pulls the image if it is missing, so one click
                        # both downloads and starts Envoy; its `start` event then
                        # announces reachability.
                        store_action=DockerImageRunAction(image=ENVOY_IMAGE_ID),
                    ),
                ],
            ),
        ),
    )


def _envoy_running() -> bool:
    """Whether an Envoy container is currently running (blocking Docker I/O)."""
    client = docker.from_env()
    try:
        container = find_container(client, image_path=IMAGES[ENVOY_IMAGE_ID].path)
    except docker.errors.DockerException:
        return False
    else:
        return container is not None and container.status == 'running'
    finally:
        client.close()


def _envoy_image_present() -> bool:
    """Whether Envoy's image is already local (blocking Docker I/O).

    The shipped device image preloads it (see
    `scripts/packer/load-bundled-docker-images.sh`), so this is what lets boot
    start Envoy there without ever pulling on an install that lacks it.
    """
    client = docker.from_env()
    try:
        client.images.get(IMAGES[ENVOY_IMAGE_ID].full_path)
    except docker.errors.DockerException:
        return False
    else:
        return True
    finally:
        client.close()


async def _handle_grpc_enabled() -> None:
    """Expose via Envoy when gRPC access is enabled, else prompt to install it.

    Nothing is exposed unless Envoy is running, so a down Envoy is not restarted
    behind the user's back — instead the prompt offers to download+start it. A
    running Envoy gets the listener rendered and reloaded; that restart's `start`
    event announces reachability.
    """
    if should_prompt_envoy(envoy_running=await asyncio.to_thread(_envoy_running)):
        _prompt_envoy_needed()
    else:
        await _apply_envoy()


async def _handle_grpc_disabled() -> None:
    """Re-render the listener-free config and reload when gRPC access is off."""
    await _withdraw_uborpc()
    if await asyncio.to_thread(_envoy_running):
        await _apply_envoy()


@store.autorun(lambda state: state.settings.grpc_remote_access)
def _on_grpc_remote_access_changed(enabled: bool) -> None:  # noqa: FBT001
    """React to genuine `grpc_remote_access` toggles (never the boot hydration)."""
    previous = _grpc_enabled[0]
    _grpc_enabled[0] = enabled
    if not _grpc_toggle_ready[0]:
        # Still booting: record the value (for the start hook) but never act, so
        # the persisted-value hydration can't masquerade as a user toggle.
        return
    transition = classify_grpc_toggle(previous=previous, current=enabled)
    if transition is GrpcToggle.ENABLE:
        create_task(_handle_grpc_enabled())
    elif transition is GrpcToggle.DISABLE:
        create_task(_handle_grpc_disabled())


def _on_envoy_started() -> None:
    """Envoy started: mDNS-advertise + announce reachability if gRPC access is on."""
    _envoy_up[0] = True
    boot_start = _boot_envoy_start[0]
    _boot_envoy_start[0] = False
    if bool(_grpc_enabled[0]):
        create_task(_advertise_uborpc())
    if should_announce_exposed(
        grpc_enabled=bool(_grpc_enabled[0]),
        boot_start=boot_start,
    ):
        _announce_grpc_reachable()


register_container_start_hook(ENVOY_IMAGE_ID, _on_envoy_started)


@store.autorun(
    lambda state: state.ip.interfaces if hasattr(state, 'ip') else None,
)
def _on_lan_ip_changed(_: Sequence[IpNetworkInterface] | None) -> None:
    """Re-advertise the gRPC API when the LAN address appears or changes.

    `_advertise_uborpc` silently no-ops without a LAN IP, and at boot that is a
    real race: on a cold Ethernet start DHCP may not have completed by the time
    Envoy's `start` event fires, which would leave the pod permanently
    undiscoverable. This also covers a DHCP lease change and the cable being
    plugged in after boot. `register_service` replaces any prior registration,
    so re-advertising needs no unregister first.
    """
    ip = _lan_ip()
    if ip == _advertised_ip[0]:
        return
    if not (bool(_grpc_enabled[0]) and _envoy_up[0]):
        return
    create_task(_advertise_uborpc() if ip else _withdraw_uborpc())


# The (exposure, credentials-revision) pair the broker was last rendered for.
# `None` until the first autorun pass, which only adopts the current value:
# without that, every boot would recreate a perfectly good Home Assistant.
_broker_settings_applied: list[tuple[bool, int] | None] = [None]

_BROKER_RECREATABLE_STATUSES = (
    DockerItemStatus.CREATED,
    DockerItemStatus.STARTING,
    DockerItemStatus.RUNNING,
)


@store.autorun(
    lambda state: (
        getattr(getattr(state, 'mqtt', None), 'bundled_expose_to_lan', False),
        getattr(getattr(state, 'mqtt', None), 'bundled_credentials_revision', 0),
        getattr(
            getattr(state.docker, HOME_ASSISTANT_COMPOSITION_ID, None),
            'status',
            None,
        ),
    ),
)
def _reconcile_bundled_broker(data: tuple[bool, int, DockerItemStatus | None]) -> None:
    """Recreate Home Assistant when the bundled broker's settings change.

    Mosquitto's config and password file are derived artifacts, and both
    `ports:` and `password_file` are read only when the container is *created*
    — so a changed password or exposure has to recreate the composition, which
    `DockerImageRunAction` does (re-render, then `up -d`).

    The MQTT slice is read through `getattr` because that service can be
    disabled, and `state.mqtt` raises rather than returning None when its slice
    is absent — the mirror of how `050-mqtt` reads the docker slice.
    """
    expose_to_lan, revision, status = data
    current = (expose_to_lan, revision)
    if _broker_settings_applied[0] is None:
        _broker_settings_applied[0] = current
        return
    if current == _broker_settings_applied[0]:
        return
    _broker_settings_applied[0] = current
    if status in _BROKER_RECREATABLE_STATUSES:
        store.dispatch(DockerImageRunAction(image=HOME_ASSISTANT_COMPOSITION_ID))


async def init_service() -> Subscriptions:
    """Initialize the service."""
    # Register apps menu title
    unregister_title = register_apps_menu_title('Apps')

    # Register path matcher for Docker navigation (apps and settings)
    unregister_path_matcher = register_path_menu_matcher(
        'docker:paths',
        _docker_path_matcher,
    )

    register_persistent_store(
        'docker_usernames',
        lambda state: state.docker.service.usernames,
    )

    register_persistent_store(
        'docker_expose_to_lan',
        lambda state: state.docker.service.expose_to_lan,
    )

    register_persistent_store(
        'docker_zigbee_enabled',
        lambda state: state.docker.service.zigbee_enabled,
    )

    register_persistent_store(
        'docker_zigbee_adapter_by_id',
        lambda state: state.docker.service.zigbee_adapter_by_id,
    )

    register_persistent_store(
        'docker_host_network_enabled',
        lambda state: state.docker.service.host_network_enabled,
    )

    from ubo_app.store.core.action_registry import register_action

    register_action('docker:import_composition', input_docker_composition)
    store.dispatch(
        RegisterRegularAppAction(
            priority=1,
            label='Add New App',
            icon='󰋺',
            background_color=WARNING_COLOR,
            action_id='docker:import_composition',
            key='_import',
            app_category=APPS_ROOT_CATEGORY,
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
        store.subscribe_event(DockerImageRebindEvent, handle_rebind),
    ]

    # Subscribed here rather than at import: a module-level `@store.autorun`
    # registers a listener the moment the file is imported, which leaks one per
    # import in tests and survives a failed `init_service` in production.
    open_logs = store.autorun(open_logs_image)(sync_log_tail)

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

    # Boot has settled and the persisted gRPC setting has hydrated: from here on,
    # `grpc_remote_access` changes are genuine user toggles the handler acts on.
    _grpc_toggle_ready[0] = True

    # Unlike the reachability notification (deliberately not re-shown for an
    # already-running Envoy), the mDNS advertisement has to be re-established
    # every process start regardless — it lives in this process's memory, so
    # a restart with gRPC access already on and Envoy already up would
    # otherwise leave it silently unadvertised until the next toggle.
    #
    # And when gRPC access is on but Envoy is down, boot starts it: the setting
    # is on by default, so on a fresh pod nothing else ever would, and the
    # setting would expose nothing. Gated on the image already being local so
    # this never pulls over the network unprompted — see
    # `should_start_envoy_at_boot`.
    grpc_enabled = bool(_grpc_enabled[0])
    envoy_running = grpc_enabled and await asyncio.to_thread(_envoy_running)
    if grpc_enabled and envoy_running:
        _envoy_up[0] = True
        create_task(_advertise_uborpc())
    elif should_start_envoy_at_boot(
        grpc_enabled=grpc_enabled,
        envoy_running=envoy_running,
        # Only asked when it can matter, so an opted-out pod does no Docker I/O.
        image_present=grpc_enabled and await asyncio.to_thread(_envoy_image_present),
    ):
        _boot_envoy_start[0] = True
        store.dispatch(DockerImageRunAction(image=ENVOY_IMAGE_ID))

    return [
        *subscriptions,
        unregister_title,
        unregister_path_matcher,
        open_logs.unsubscribe,
        stop_log_tail,
        _withdraw_uborpc,
    ]
