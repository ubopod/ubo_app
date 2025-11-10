"""Docker image management."""

from __future__ import annotations

from dataclasses import replace

import docker
import docker.errors
from calculate_progress import LayerProgressTracker
from docker_images import IMAGES

from ubo_app.colors import DANGER_COLOR
from ubo_app.constants import DOCKER_CREDENTIALS_TEMPLATE_SECRET_ID
from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.docker import (
    DockerImageFetchEvent,
    DockerImageRemoveEvent,
    DockerImageSetStatusAction,
    DockerItemStatus,
)
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.utils import secrets
from ubo_app.utils.async_ import to_thread

# Notification IDs for progress tracking
DOCKER_FETCH_PROGRESS_NOTIFICATION_ID = 'docker:fetch_progress:{}'


def _create_fetch_progress_notification(
    image_id: str,
    content: str = 'Starting download...',
    progress: float | None = 0.0,
) -> Notification:
    """Create a fetch progress notification for an image."""
    return Notification(
        id=DOCKER_FETCH_PROGRESS_NOTIFICATION_ID.format(image_id),
        title=f'{IMAGES[image_id].label}',
        content=content,
        display_type=NotificationDisplayType.BACKGROUND,
        icon=IMAGES[image_id].icon,
        show_dismiss_action=False,
        progress=progress,
    )


def get_full_image_path(image_id: str) -> str:
    """Get full image path including registry if specified."""
    image_entry = IMAGES[image_id]
    if image_entry.registry:
        return f'{image_entry.registry}/{image_entry.path}'
    return image_entry.path


@store.with_state(lambda state: state.docker.service.usernames)
def fetch_image(  # noqa: C901
    usernames: dict[str, str],
    event: DockerImageFetchEvent,
) -> None:
    """Fetch an image."""
    id = event.image

    def act() -> None:
        # Create base notification
        base_notification = _create_fetch_progress_notification(id)

        # Dispatch initial status and notification
        store.dispatch(
            DockerImageSetStatusAction(
                image=id,
                status=DockerItemStatus.FETCHING,
            ),
            NotificationsAddAction(notification=base_notification),
        )

        try:
            # Construct full image path with registry if specified
            image_entry = IMAGES[id]
            if image_entry.registry:
                full_image_path = f'{image_entry.registry}/{image_entry.path}'
            else:
                full_image_path = image_entry.path

            logger.info('Fetching image', extra={'full_path': full_image_path})
            docker_client = docker.from_env()

            # Login to registry if credentials are available
            for registry, username in usernames.items():
                if image_entry.registry == registry:
                    docker_client.login(
                        username=username,
                        password=secrets.read_secret(
                            DOCKER_CREDENTIALS_TEMPLATE_SECRET_ID.format(registry),
                        ),
                        registry=registry,
                    )

            # Pull the image with progress tracking
            logger.info(
                'Starting image pull',
                extra={'full_path': full_image_path, 'image': id},
            )
            pull_result = docker_client.api.pull(
                full_image_path,
                stream=True,
                decode=True,
            )

            # Initialize progress tracker
            progress_tracker = LayerProgressTracker(id)

            for line in pull_result:
                if 'status' in line:
                    layer_id = line.get('id', 'unknown')
                    status = line['status']
                    progress = line.get('progress', '')

                    # Update progress tracker
                    progress_tracker.update_layer(layer_id, status, progress)

                    # Update UI periodically (debounced)
                    if progress_tracker.should_update_ui():
                        current_progress = progress_tracker.calculate_progress()
                        store.dispatch(
                            NotificationsAddAction(
                                notification=replace(
                                    base_notification,
                                    content='Downloading image...',
                                    progress=current_progress,
                                ),
                            ),
                        )

                    # Log significant status changes
                    if status in (
                        'Downloading',
                        'Extracting',
                        'Pull complete',
                        'Already exists',
                    ):
                        logger.debug(
                            'Image pull progress',
                            extra={
                                'image': id,
                                'layer': layer_id,
                                'status': status,
                                'progress': progress,
                            },
                        )

                if 'error' in line:
                    error_msg = line['error']
                    logger.error(
                        'Image pull error',
                        extra={'image': id, 'error': error_msg},
                    )
                    msg = f'Pull failed: {error_msg}'
                    raise docker.errors.ImageNotFound(msg)

            logger.info('Image pull completed', extra={'image': id})
            docker_client.close()

            # Dispatch success notification
            store.dispatch(
                NotificationsAddAction(
                    notification=replace(
                        base_notification,
                        content='Download complete!',
                        progress=1.0,
                        show_dismiss_action=True,
                        display_type=NotificationDisplayType.FLASH,
                        dismiss_on_close=True,
                        chime=Chime.DONE,
                    ),
                ),
            )
        except docker.errors.DockerException as e:
            logger.exception(
                'Failed to fetch image',
                extra={'image': id, 'error': str(e)},
            )
            store.dispatch(
                DockerImageSetStatusAction(
                    image=id,
                    status=DockerItemStatus.ERROR,
                ),
                NotificationsAddAction(
                    notification=replace(
                        base_notification,
                        display_type=NotificationDisplayType.FLASH,
                        content='Download failed',
                        color=DANGER_COLOR,
                        show_dismiss_action=True,
                        progress=None,
                        chime=Chime.FAILURE,
                    ),
                ),
                NotificationsAddAction(
                    notification=Notification(
                        id=f'docker_fetch_error_{id}',
                        title=f'Failed to Fetch {IMAGES[id].label}',
                        content=f'Error: {str(e).split("(")[0].strip()}',
                        display_type=NotificationDisplayType.STICKY,
                        color=DANGER_COLOR,
                        icon=IMAGES[id].icon,
                        chime=Chime.FAILURE,
                    ),
                ),
            )
            raise

    to_thread(act)


def remove_image(event: DockerImageRemoveEvent) -> None:
    """Remove an image."""
    id = event.image
    docker_client = docker.from_env()
    docker_client.images.remove(get_full_image_path(id), force=True)
    docker_client.close()
