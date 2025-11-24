"""Shared utilities for Docker app operations (containers and compositions)."""

from __future__ import annotations

import json
from inspect import iscoroutine

from docker_composition import COMPOSITIONS_PATH
from docker_images import IMAGES

from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.docker import DockerImageUpdateMetadataAction


async def prepare_app(id: str) -> bool:
    """Prepare an app (container or composition) for use.

    This function:
    1. Checks if a prepare function exists for the app
    2. Calls it (handling both sync and async functions)
    3. Checks the boolean result
    4. For compositions, updates metadata in Redux store
    5. Returns success/failure

    Parameters
    ----------
    id : str
        The app/image ID

    Returns
    -------
    bool
        True if preparation succeeded or no preparation needed, False otherwise

    """
    prepare_function = IMAGES[id].prepare
    if not prepare_function:
        return True

    logger.info(
        'Preparing app',
        extra={'image': id, 'is_composition': IMAGES[id].is_composition},
    )

    result = prepare_function()
    if iscoroutine(result):
        result = await result

    if not result:
        logger.error('Failed to prepare app', extra={'image': id})
        return False

    # Update metadata for compositions
    if IMAGES[id].is_composition:
        await update_composition_metadata(id)

    return True


async def update_composition_metadata(id: str) -> None:
    """Load and dispatch metadata for a composition.

    Reads the metadata.json file created by the prepare function
    and dispatches an action to update the Redux store with instructions
    and other metadata.

    Parameters
    ----------
    id : str
        The composition ID

    """
    metadata_path = COMPOSITIONS_PATH / id / 'metadata.json'
    if not metadata_path.exists():
        logger.warning(
            'Metadata file not found for composition',
            extra={'image': id, 'path': str(metadata_path)},
        )
        return

    try:
        metadata = json.load(metadata_path.open())
        store.dispatch(
            DockerImageUpdateMetadataAction(
                image=id,
                instructions=metadata.get('instructions'),
            ),
        )
        logger.info(
            'Updated composition metadata',
            extra={'image': id, 'has_instructions': bool(metadata.get('instructions'))},
        )
    except Exception:
        logger.exception(
            'Failed to load composition metadata',
            extra={'image': id, 'path': str(metadata_path)},
        )
