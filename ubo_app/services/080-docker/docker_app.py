"""Shared utilities for Docker app operations (containers and compositions)."""

from __future__ import annotations

import json
from inspect import iscoroutine
from typing import TYPE_CHECKING

from docker_composition import COMPOSITIONS_PATH

from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.docker import DockerImageUpdateMetadataAction

if TYPE_CHECKING:
    from docker_images import ContainerEntry


async def prepare_app(container: ContainerEntry) -> bool:
    """Prepare an app (container or composition) for use.

    This function:
    1. Checks if a prepare function exists for the app
    2. Calls it (handling both sync and async functions)
    3. Checks the boolean result
    4. For compositions, updates metadata in Redux store
    5. Returns success/failure

    Parameters
    ----------
    container : ContainerEntry
        The container entry to prepare

    Returns
    -------
    bool
        True if preparation succeeded or no preparation needed, False otherwise

    """
    prepare_function = container.prepare
    if not prepare_function:
        return True

    logger.info(
        'Preparing app',
        extra={'image': container.id, 'is_composition': container.is_composition},
    )

    result = prepare_function()
    if iscoroutine(result):
        result = await result

    if not result:
        logger.error('Failed to prepare app', extra={'image': container.id})
        return False

    # Update metadata for compositions
    if container.is_composition:
        await update_composition_metadata(container)

    return True


async def update_composition_metadata(container: ContainerEntry) -> None:
    """Load and dispatch metadata for a composition.

    Reads the metadata.json file created by the prepare function
    and dispatches an action to update the Redux store with instructions
    and other metadata.

    Parameters
    ----------
    container : ContainerEntry
        The container entry for the composition

    """
    metadata_path = COMPOSITIONS_PATH / container.id / 'metadata.json'
    if not metadata_path.exists():
        logger.warning(
            'Metadata file not found for composition',
            extra={'image': container.id, 'path': str(metadata_path)},
        )
        return

    try:
        metadata = json.load(metadata_path.open())
        store.dispatch(
            DockerImageUpdateMetadataAction(
                image=container.id,
                instructions=metadata.get('instructions'),
            ),
        )
        logger.info(
            'Updated composition metadata',
            extra={
                'image': container.id,
                'has_instructions': bool(metadata.get('instructions')),
            },
        )
    except Exception:
        logger.exception(
            'Failed to load composition metadata',
            extra={'image': container.id, 'path': str(metadata_path)},
        )
