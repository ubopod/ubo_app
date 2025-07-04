"""Docker reducer."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

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
    DockerImageFetchAction,
    DockerImageFetchCompositionAction,
    DockerImageFetchCompositionEvent,
    DockerImageFetchEvent,
    DockerImageRegisterAppEvent,
    DockerImageReleaseCompositionAction,
    DockerImageReleaseCompositionEvent,
    DockerImageRemoveAction,
    DockerImageRemoveCompositionAction,
    DockerImageRemoveCompositionEvent,
    DockerImageRemoveContainerAction,
    DockerImageRemoveContainerEvent,
    DockerImageRemoveEvent,
    DockerImageRunCompositionAction,
    DockerImageRunCompositionEvent,
    DockerImageRunContainerAction,
    DockerImageRunContainerEvent,
    DockerImageSetDockerIdAction,
    DockerImageSetStatusAction,
    DockerImageStopCompositionAction,
    DockerImageStopCompositionEvent,
    DockerImageStopContainerAction,
    DockerImageStopContainerEvent,
    DockerInstallAction,
    DockerInstallEvent,
    DockerItemStatus,
    DockerRemoveUsernameAction,
    DockerServiceState,
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

    match action:
        case DockerSetStatusAction():
            return replace(state, status=action.status)

        case DockerStoreUsernameAction():
            return replace(
                state,
                usernames={**state.usernames, action.registry: action.username},
            )

        case DockerRemoveUsernameAction():
            return replace(
                state,
                usernames={
                    registry: username
                    for registry, username in state.usernames.items()
                    if registry != action.registry
                },
            )

        case DockerInstallAction():
            return CompleteReducerResult(
                state=replace(state, status=DockerStatus.INSTALLING),
                events=[DockerInstallEvent()],
            )

        case DockerStartAction():
            return CompleteReducerResult(
                state=replace(state, status=DockerStatus.UNKNOWN),
                events=[DockerStartEvent()],
            )

        case DockerStopAction():
            return CompleteReducerResult(
                state=replace(state, status=DockerStatus.UNKNOWN),
                events=[DockerStopEvent()],
            )

        case _:
            return state


def image_reducer(
    state: ImageState | None,
    action: DockerImageAction | CombineReducerAction | IpUpdateInterfacesAction,
) -> ReducerResult[ImageState | None, BaseAction, BaseEvent]:
    """Image reducer."""
    if state is None:
        if (
            isinstance(action, CombineReducerInitAction)
            and action.payload
            and 'label' in action.payload
        ):
            return CompleteReducerResult(
                state=ImageState(
                    id=action.key,
                    label=action.payload['label'],
                    instructions=action.payload.get('instructions', None),
                ),
                events=[DockerImageRegisterAppEvent(image=action.key)],
            )
        raise InitializationActionError(action)

    if not isinstance(action, DockerImageAction) or action.image != state.id:
        return state

    match action:
        case DockerImageSetStatusAction():
            return replace(
                state,
                status=action.status,
                ports=action.ports if action.ports else state.ports,
                container_ip=action.ip,
            )

        case DockerImageSetDockerIdAction():
            return replace(state, docker_id=action.docker_id)

        case DockerImageFetchCompositionAction():
            return CompleteReducerResult(
                state=state,
                events=[DockerImageFetchCompositionEvent(image=state.id)],
            )

        case DockerImageFetchAction():
            return CompleteReducerResult(
                state=replace(state, status=DockerItemStatus.FETCHING),
                events=[DockerImageFetchEvent(image=state.id)],
            )

        case DockerImageRemoveCompositionAction():
            return CompleteReducerResult(
                state=state,
                events=[DockerImageRemoveCompositionEvent(image=state.id)],
            )

        case DockerImageRemoveAction():
            return CompleteReducerResult(
                state=state,
                events=[DockerImageRemoveEvent(image=state.id)],
            )

        case DockerImageRunCompositionAction():
            return CompleteReducerResult(
                state=state,
                events=[DockerImageRunCompositionEvent(image=state.id)],
            )

        case DockerImageRunContainerAction():
            return CompleteReducerResult(
                state=state,
                events=[DockerImageRunContainerEvent(image=state.id)],
            )

        case DockerImageStopCompositionAction():
            return CompleteReducerResult(
                state=state,
                events=[DockerImageStopCompositionEvent(image=state.id)],
            )

        case DockerImageStopContainerAction():
            return CompleteReducerResult(
                state=state,
                events=[DockerImageStopContainerEvent(image=state.id)],
            )

        case DockerImageReleaseCompositionAction():
            return CompleteReducerResult(
                state=state,
                events=[DockerImageReleaseCompositionEvent(image=state.id)],
            )

        case DockerImageRemoveContainerAction():
            return CompleteReducerResult(
                state=state,
                events=[DockerImageRemoveContainerEvent(image=state.id)],
            )

        case _:
            return state

    return state


reducer, reducer_id = combine_reducers(
    state_type=DockerState,
    action_type=DockerImageAction,
    event_type=DockerImageEvent,
    service=service_reducer,
)
