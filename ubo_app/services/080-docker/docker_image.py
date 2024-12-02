"""Docker image management."""

from __future__ import annotations

from typing import TYPE_CHECKING

import docker
import docker.errors
from docker_images import IMAGES

from ubo_app.constants import DOCKER_CREDENTIALS_TEMPLATE
from ubo_app.logging import logger
from ubo_app.store.main import store
from ubo_app.store.services.docker import DockerImageSetStatusAction, DockerItemStatus
from ubo_app.utils import secrets
from ubo_app.utils.async_ import to_thread

if TYPE_CHECKING:
    from ubo_app.store.services.docker import ImageState


@store.view(lambda state: state.docker.service.usernames)
def fetch_image(usernames: dict[str, str], image: ImageState) -> None:
    """Fetch an image."""

    def act() -> None:
        store.dispatch(
            DockerImageSetStatusAction(
                image=image.id,
                status=DockerItemStatus.FETCHING,
            ),
        )
        try:
            logger.info('Fetching image', extra={'image': IMAGES[image.id].path})
            docker_client = docker.from_env()
            for registry, username in usernames.items():
                if IMAGES[image.id].registry == registry:
                    docker_client.login(
                        username=username,
                        password=secrets.read_secret(
                            DOCKER_CREDENTIALS_TEMPLATE.format(registry),
                        ),
                        registry=registry,
                    )
            docker_client.images.pull(IMAGES[image.id].path)
            docker_client.close()
        except docker.errors.DockerException:
            logger.exception(
                'Image error',
                extra={'image': image.id, 'path': IMAGES[image.id].path},
            )
            store.dispatch(
                DockerImageSetStatusAction(
                    image=image.id,
                    status=DockerItemStatus.ERROR,
                ),
            )

    to_thread(act)


def remove_image(image: ImageState) -> None:
    """Remove an image."""

    def act() -> None:
        docker_client = docker.from_env()
        docker_client.images.remove(IMAGES[image.id].path, force=True)
        docker_client.close()

    to_thread(act)
