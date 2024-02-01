"""Docker reducer."""
from __future__ import annotations

from dataclasses import asdict, replace

from immutable import Immutable
from redux import (
    BaseEvent,
    CombineReducerAction,
    CombineReducerInitAction,
    InitAction,
    InitializationActionError,
    ReducerResult,
    combine_reducers,
)

from ubo_app.store.services.docker import (
    DockerAction,
    DockerImageAction,
    DockerImageEvent,
    DockerImageSetStatusAction,
    DockerServiceState,
    DockerSetStatusAction,
    DockerState,
    ImageState,
)

Action = InitAction | DockerAction


def service_reducer(
    state: DockerServiceState | None,
    action: Action,
) -> ReducerResult[DockerServiceState, Action, BaseEvent]:
    """Docker reducer."""
    if state is None:
        if isinstance(action, InitAction):
            return DockerServiceState()
        raise InitializationActionError(action)

    if isinstance(action, DockerSetStatusAction):
        return replace(state, status=action.status)

    return state


class ImageEntry(Immutable):
    """An image to be used in a Docker container."""

    id: str
    label: str
    icon: str
    path: str


IMAGES = {
    image.id: image
    for image in [
        ImageEntry(
            id='home_assistant',
            label='Home Assistant',
            icon='home',
            path='homeassistant/home-assistant:stable',
        ),
        ImageEntry(
            id='home_bridge',
            label='Home Bridge',
            icon='home_work',
            path='homebridge/homebridge:latest',
        ),
        ImageEntry(
            id='portainer',
            label='Portainer',
            icon='settings_applications',
            path='portainer/portainer-ce:latest',
        ),
        ImageEntry(
            id='pi_hole',
            label='Pi-hole',
            icon='dns',
            path='pihole/pihole:latest',
        ),
    ]
}
IMAGE_IDS = list(IMAGES.keys())


def image_reducer(
    state: ImageState | None,
    action: DockerImageAction | CombineReducerAction,
) -> ImageState:
    """Image reducer."""
    if state is None:
        if isinstance(action, CombineReducerInitAction):
            return ImageState(**asdict(IMAGES[action.key]))
        raise InitializationActionError(action)

    if not isinstance(action, DockerImageAction) or action.image != state.id:
        return state

    if isinstance(action, DockerImageSetStatusAction):
        return replace(state, status=action.status)

    return state


reducer, reducer_id = combine_reducers(
    state_type=DockerState,
    action_type=DockerImageAction,
    event_type=DockerImageEvent,
    service=service_reducer,
    **{image: image_reducer for image in IMAGE_IDS},
)
