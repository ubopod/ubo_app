"""Docker reducer."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from apps import IMAGES
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
    DockerImageFetchCompositionEvent,
    DockerImageFetchEvent,
    DockerImageRebindEvent,
    DockerImageRegisterAppEvent,
    DockerImageReleaseAction,
    DockerImageReleaseCompositionEvent,
    DockerImageRemoveAction,
    DockerImageRemoveCompositionEvent,
    DockerImageRemoveContainerAction,
    DockerImageRemoveContainerEvent,
    DockerImageRemoveEvent,
    DockerImageReportExitAction,
    DockerImageRunAction,
    DockerImageRunCompositionEvent,
    DockerImageRunContainerEvent,
    DockerImageSetDockerIdAction,
    DockerImageSetExposeToLanAction,
    DockerImageSetStatusAction,
    DockerImageStopAction,
    DockerImageStopCompositionEvent,
    DockerImageStopContainerEvent,
    DockerImageUpdateMetadataAction,
    DockerInstallAction,
    DockerInstallEvent,
    DockerItemStatus,
    DockerRemoveUsernameAction,
    DockerServiceState,
    DockerSetHostNetworkAction,
    DockerSetStatusAction,
    DockerSetZigbeeIntentAction,
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

        case DockerImageSetExposeToLanAction():
            return CompleteReducerResult(
                state=replace(
                    state,
                    expose_to_lan={
                        **state.expose_to_lan,
                        action.image: action.expose_to_lan,
                    },
                ),
                events=[DockerImageRebindEvent(image=action.image)],
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

        case DockerSetZigbeeIntentAction():
            return replace(
                state,
                zigbee_enabled=action.enabled,
                zigbee_adapter_by_id=action.adapter_by_id,
            )

        case DockerSetHostNetworkAction():
            return replace(state, host_network_enabled=action.enabled)

        case _:
            return state


def _without_exit_record(state: ImageState) -> ImageState:
    """Drop the latched crash record, leaving the lifecycle status alone."""
    return replace(
        state,
        restart_count=0,
        last_exit_code=None,
        last_exit_at=None,
        last_error='',
        failing_services=(),
    )


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
            new_status = action.status
            if (
                new_status == DockerItemStatus.STARTING
                and state.status == DockerItemStatus.RUNNING
            ):
                new_status = DockerItemStatus.RUNNING
            return replace(
                state,
                status=new_status,
                ports=action.ports if action.ports else state.ports,
                container_ip=action.ip,
            )

        case DockerImageReportExitAction():
            return replace(
                state,
                restart_count=action.restart_count,
                last_exit_code=action.exit_code,
                last_exit_at=action.exit_at,
                last_error=action.error,
                failing_services=action.failing_services,
            )

        case DockerImageSetDockerIdAction():
            return replace(state, docker_id=action.docker_id)

        case DockerImageUpdateMetadataAction():
            return replace(
                state,
                instructions=action.instructions
                if action.instructions is not None
                else state.instructions,
            )

        case DockerImageFetchAction():
            if IMAGES[state.id].is_composition:
                return CompleteReducerResult(
                    state=replace(state, status=DockerItemStatus.FETCHING),
                    events=[DockerImageFetchCompositionEvent(image=state.id)],
                )
            return CompleteReducerResult(
                state=replace(state, status=DockerItemStatus.FETCHING),
                events=[DockerImageFetchEvent(image=state.id)],
            )

        case DockerImageRemoveAction():
            if IMAGES[state.id].is_composition:
                return CompleteReducerResult(
                    state=state,
                    events=[DockerImageRemoveCompositionEvent(image=state.id)],
                )
            return CompleteReducerResult(
                state=state,
                events=[DockerImageRemoveEvent(image=state.id)],
            )

        case DockerImageRunAction():
            # Starting or stopping by hand is the user acknowledging whatever
            # the app did last, so the crash record goes with it. A manual start
            # also resets the daemon's own counter, so keeping it would only
            # disagree with the next reading.
            if IMAGES[state.id].is_composition:
                return CompleteReducerResult(
                    state=_without_exit_record(state),
                    events=[DockerImageRunCompositionEvent(image=state.id)],
                )
            return CompleteReducerResult(
                state=_without_exit_record(state),
                events=[DockerImageRunContainerEvent(image=state.id)],
            )

        case DockerImageStopAction():
            if IMAGES[state.id].is_composition:
                return CompleteReducerResult(
                    state=_without_exit_record(state),
                    events=[DockerImageStopCompositionEvent(image=state.id)],
                )
            return CompleteReducerResult(
                state=_without_exit_record(state),
                events=[DockerImageStopContainerEvent(image=state.id)],
            )

        case DockerImageReleaseAction():
            return CompleteReducerResult(
                state=state,
                events=[DockerImageReleaseCompositionEvent(image=state.id)],
            )

        case DockerImageRemoveContainerAction():
            return CompleteReducerResult(
                state=_without_exit_record(state),
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
