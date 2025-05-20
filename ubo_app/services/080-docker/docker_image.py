"""Docker image management."""

from __future__ import annotations

import docker
import docker.errors
from docker_images import IMAGES

from ubo_app.constants import DOCKER_CREDENTIALS_TEMPLATE
from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.docker import (
    DockerImageFetchEvent,
    DockerImageRemoveEvent,
    DockerImageSetStatusAction,
    DockerItemStatus,
)
from ubo_app.utils import secrets


@store.with_state(lambda state: state.docker.service.usernames)
def fetch_image(
    usernames: dict[str, str],
    event: DockerImageFetchEvent,
) -> None:
    """Fetch an image."""
    id = event.image

    store.dispatch(
        DockerImageSetStatusAction(
            image=id,
            status=DockerItemStatus.FETCHING,
        ),
    )
    try:
        logger.info('Fetching image', extra={'image': IMAGES[id].path})
        docker_client = docker.from_env()
        for registry, username in usernames.items():
            if IMAGES[id].registry == registry:
                docker_client.login(
                    username=username,
                    password=secrets.read_secret(
                        DOCKER_CREDENTIALS_TEMPLATE.format(registry),
                    ),
                    registry=registry,
                )
        docker_client.images.pull(IMAGES[id].path)
        docker_client.close()
    except docker.errors.DockerException:
        store.dispatch(
            DockerImageSetStatusAction(
                image=id,
                status=DockerItemStatus.ERROR,
            ),
        )
        raise


def remove_image(event: DockerImageRemoveEvent) -> None:
    """Remove an image."""
    id = event.image
    docker_client = docker.from_env()
    docker_client.images.remove(IMAGES[id].path, force=True)
    docker_client.close()
