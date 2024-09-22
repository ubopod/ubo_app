"""Docker reducer."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from images_ import IMAGE_IDS, IMAGES
from redux import (
    BaseAction,
    BaseEvent,
    CombineReducerAction,
    CombineReducerInitAction,
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
    combine_reducers,
)

from ubo_app.store.services.docker import (
    DockerAction,
    DockerImageAction,
    DockerImageEvent,
    DockerImageRegisterAppEvent,
    DockerImageSetDockerIdAction,
    DockerImageSetStatusAction,
    DockerRemoveUsernameAction,
    DockerServiceState,
    DockerSetStatusAction,
    DockerState,
    DockerStoreUsernameAction,
    ImageState,
)

if TYPE_CHECKING:
    from ubo_app.store.services.ip import IpUpdateInterfacesAction

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

    if isinstance(action, DockerStoreUsernameAction):
        return replace(
            state,
            usernames={**state.usernames, action.registry: action.username},
        )

    if isinstance(action, DockerRemoveUsernameAction):
        return replace(
            state,
            usernames={
                registry: username
                for registry, username in state.usernames.items()
                if registry != action.registry
            },
        )

    return state


def image_reducer(
    state: ImageState | None,
    action: DockerImageAction | CombineReducerAction | IpUpdateInterfacesAction,
) -> ReducerResult[ImageState, BaseAction, BaseEvent]:
    """Image reducer."""
    if state is None:
        if isinstance(action, CombineReducerInitAction):
            image = IMAGES[action.key]
            return CompleteReducerResult(
                state=ImageState(id=image.id),
                events=[DockerImageRegisterAppEvent(image=image.id)],
            )
        raise InitializationActionError(action)

    if not isinstance(action, DockerImageAction) or action.image != state.id:
        return state

    if isinstance(action, DockerImageSetStatusAction):
        return replace(
            state,
            status=action.status,
            ports=action.ports if action.ports else state.ports,
            container_ip=action.ip,
        )

    if isinstance(action, DockerImageSetDockerIdAction):
        return replace(state, docker_id=action.docker_id)

    return state


reducer, reducer_id = combine_reducers(
    state_type=DockerState,
    action_type=DockerImageAction,
    event_type=DockerImageEvent,
    service=service_reducer,
    **{image: image_reducer for image in IMAGE_IDS},
)
