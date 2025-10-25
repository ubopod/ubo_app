"""Docker preset installer for one-click composition setup."""

from __future__ import annotations

import json
import secrets as py_secrets
import string
import uuid
from typing import TYPE_CHECKING

import aiohttp
from docker_composition import COMPOSITIONS_PATH, check_composition
from redux import CombineReducerRegisterAction

from ubo_app.colors import DANGER_COLOR, SUCCESS_COLOR, WARNING_COLOR
from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.docker import (
    DockerImageSetStatusAction,
    DockerItemStatus,
    DockerPresetInstallEvent,
)
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.utils import secrets
from ubo_app.utils.async_ import create_task

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from docker_presets import CredentialConfig, PresetCompositionEntry
    from redux import BaseAction, BaseEvent, CombineReducerAction, ReducerResult

    from ubo_app.store.services.docker import DockerImageAction, ImageState
    from ubo_app.store.services.ip import IpUpdateInterfacesAction

    ImageReducerType = Callable[
        [
            ImageState | None,
            DockerImageAction | CombineReducerAction | IpUpdateInterfacesAction,
        ],
        ReducerResult[ImageState | None, BaseAction, BaseEvent],
    ]



def generate_credential(config: CredentialConfig) -> str:
    """Generate a secure credential based on config."""
    if config.type == 'uuid':
        return uuid.uuid4().hex

    if config.type == 'username':
        # Generate alphanumeric username
        return 'user_' + ''.join(
            py_secrets.choice(string.ascii_lowercase + string.digits)
            for _ in range(config.length)
        )

    if config.type in ('password', 'token'):
        if config.charset == 'alphanumeric':
            chars = string.ascii_letters + string.digits
        elif config.charset == 'alpha':
            chars = string.ascii_letters
        elif config.charset == 'numeric':
            chars = string.digits
        elif config.charset == 'hex':
            chars = string.hexdigits.lower()
        else:
            chars = string.ascii_letters + string.digits

        return ''.join(py_secrets.choice(chars) for _ in range(config.length))

    return ''


async def download_file(url: str) -> str:
    """Download a file from URL and return its content."""
    async with aiohttp.ClientSession() as session, session.get(url) as response:
        response.raise_for_status()
        return await response.text()


def _show_install_notification(preset: PresetCompositionEntry) -> None:
    """Show notification that preset installation has started."""
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=f'preset_install_{preset.id}',
                title=f'Installing {preset.label}',
                content='Downloading configuration files...',
                display_type=NotificationDisplayType.STICKY,
                color=WARNING_COLOR,
                icon=preset.icon,
                show_dismiss_action=False,
            ),
        ),
    )


def _show_success_notification(preset: PresetCompositionEntry) -> None:
    """Show notification that preset installation succeeded."""
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=f'preset_install_{preset.id}',
                title=f'{preset.label} Installed',
                content='Configuration downloaded. Pull images to continue.',
                display_type=NotificationDisplayType.FLASH,
                color=SUCCESS_COLOR,
                icon=preset.icon,
                chime=Chime.DONE,
            ),
        ),
    )


def _show_error_notification(preset: PresetCompositionEntry) -> None:
    """Show notification that preset installation failed."""
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=f'preset_install_{preset.id}',
                title=f'{preset.label} Installation Failed',
                content='Failed to download or configure preset. Check logs.',
                display_type=NotificationDisplayType.STICKY,
                color=DANGER_COLOR,
                icon=preset.icon,
                chime=Chime.FAILURE,
            ),
        ),
    )


def process_env_template(
    preset: PresetCompositionEntry,
    env_content: str,
    credentials: dict[str, str],
    composition_path: Path,
) -> str:
    """Process .env template with generated credentials and mappings."""
    # Replace credential placeholders
    for cred_config in preset.credentials.values():
        env_var = cred_config.env_var
        cred_value = credentials.get(cred_config.secret_key, '')
        # Replace patterns like DB_PASSWORD=postgres or ${DB_PASSWORD}
        env_content = env_content.replace(
            f'{env_var}=',
            f'{env_var}={cred_value}\n# Original: ',
        )
        env_content = env_content.replace(f'${{{env_var}}}', cred_value)

    # Process env_mappings
    for env_var, mapping_value in preset.env_mappings.items():
        # Resolve callable values
        resolved_value = mapping_value() if callable(mapping_value) else mapping_value
        # Replace environment variable values
        env_content = env_content.replace(
            f'{env_var}=',
            f'{env_var}={resolved_value}\n# Original: ',
        )
        env_content = env_content.replace(f'${{{env_var}}}', str(resolved_value))

    # Update relative paths to absolute paths within composition directory
    for relative_path, target_dir in preset.path_replacements.items():
        absolute_path = composition_path / target_dir
        # Replace patterns like VARIABLE=./path
        env_content = env_content.replace(
            f'={relative_path}',
            f'={absolute_path}',
        )
        # Replace patterns like ${VARIABLE} that contain the path
        env_content = env_content.replace(relative_path, str(absolute_path))

    return env_content


async def install_preset(
    preset: PresetCompositionEntry,
    composition_id: str,
    reducer_id: str,
    image_reducer_func: ImageReducerType,
) -> None:
    """Install a preset composition with automatic setup."""
    try:
        _show_install_notification(preset)

        # Set status to fetching
        store.dispatch(
            DockerImageSetStatusAction(
                image=composition_id,
                status=DockerItemStatus.FETCHING,
            ),
        )

        # Create composition directory
        composition_path = COMPOSITIONS_PATH / composition_id
        composition_path.mkdir(exist_ok=True, parents=True)

        # Download docker-compose.yml
        logger.info(
            'Downloading docker-compose.yml',
            extra={'preset': preset.id, 'url': preset.compose_url},
        )
        compose_content = await download_file(preset.compose_url)
        (composition_path / 'docker-compose.yml').write_text(compose_content)

        # Generate credentials
        generated_credentials: dict[str, str] = {}
        for cred_config in preset.credentials.values():
            cred_value = generate_credential(cred_config)
            generated_credentials[cred_config.secret_key] = cred_value

            # Store in .secrets.env
            secrets.write_secret(key=cred_config.secret_key, value=cred_value)
            logger.info(
                'Generated and stored credential',
                extra={
                    'preset': preset.id,
                    'secret_key': cred_config.secret_key,
                    'type': cred_config.type,
                },
            )

        # Download and process .env file if provided
        if preset.env_url:
            logger.info(
                'Downloading .env template',
                extra={'preset': preset.id, 'url': preset.env_url},
            )
            env_content = await download_file(preset.env_url)
            env_content = process_env_template(
                preset,
                env_content,
                generated_credentials,
                composition_path,
            )
            (composition_path / '.env').write_text(env_content)

        # Download additional files if specified
        for file_name, url in preset.additional_files.items():
            logger.info(
                'Downloading additional file',
                extra={'preset': preset.id, 'file_name': file_name, 'url': url},
            )
            file_content = await download_file(url)
            (composition_path / file_name).write_text(file_content)

        # Create metadata.json
        metadata = {
            'label': preset.label,
            'icon': preset.icon,
            'instructions': preset.instructions,
            'preset_id': preset.id,
        }
        (composition_path / 'metadata.json').write_text(json.dumps(metadata))

        # Register the composition in Redux store
        store.dispatch(
            CombineReducerRegisterAction(
                combine_reducers_id=reducer_id,
                key=composition_id,
                reducer=image_reducer_func,
                payload=metadata,
            ),
        )

        _show_success_notification(preset)

        # Check composition status
        await check_composition(id=composition_id)

    except Exception:
        logger.exception(
            'Failed to install preset',
            extra={'preset': preset.id},
        )

        _show_error_notification(preset)
        store.dispatch(
            DockerImageSetStatusAction(
                image=composition_id,
                status=DockerItemStatus.ERROR,
            ),
        )


def handle_preset_install(
    event: DockerPresetInstallEvent,
    reducer_id: str,
    image_reducer_func: ImageReducerType,
) -> None:
    """Handle preset installation event."""
    from docker_presets import PRESET_COMPOSITIONS

    preset = PRESET_COMPOSITIONS.get(event.preset_id)
    if not preset:
        logger.error(
            'Unknown preset ID',
            extra={'preset_id': event.preset_id},
        )
        return

    composition_id = f'preset_{event.preset_id}'

    # Check if already installed
    composition_path = COMPOSITIONS_PATH / composition_id
    if composition_path.exists():
        logger.warning(
            'Preset already installed',
            extra={'preset_id': preset.id, 'path': str(composition_path)},
        )
        return

    create_task(
        install_preset(preset, composition_id, reducer_id, image_reducer_func),
    )
