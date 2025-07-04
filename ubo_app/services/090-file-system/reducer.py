# ruff: noqa: D100, D103

from __future__ import annotations

from dataclasses import replace

from constants import SELECTOR_APPLICATION_ID
from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.input.types import (
    InputAction,
    InputDemandAction,
    InputMethod,
    InputProvideAction,
    InputResolveAction,
    InputResult,
    PathInputDescription,
)
from ubo_app.store.services.file_system import (
    FileSystemAction,
    FileSystemCopyAction,
    FileSystemCopyEvent,
    FileSystemEvent,
    FileSystemMoveAction,
    FileSystemMoveEvent,
    FileSystemRemoveAction,
    FileSystemRemoveEvent,
    FileSystemReportSelectionAction,
    FileSystemSelectEvent,
    FileSystemState,
)
from ubo_app.store.services.notifications import NotificationsClearByIdAction

DispatchAction = NotificationsClearByIdAction | InputProvideAction


def pop_queue(
    state: FileSystemState,
    *,
    actions: list[DispatchAction] | None = None,
    events: list[FileSystemEvent] | None = None,
) -> ReducerResult[
    FileSystemState,
    DispatchAction,
    FileSystemEvent,
]:
    actions = actions or []
    events = events or []

    actions += [
        NotificationsClearByIdAction(
            id=SELECTOR_APPLICATION_ID.format(id=state.queue[0].id),
        ),
    ]

    _, *queue = state.queue
    if queue:
        events.append(FileSystemSelectEvent(description=queue[0]))
    return CompleteReducerResult(
        state=replace(state, queue=queue),
        actions=actions,
        events=events,
    )


def reducer(
    state: FileSystemState | None,
    action: FileSystemAction | InputAction,
) -> ReducerResult[
    FileSystemState,
    DispatchAction,
    FileSystemEvent,
]:
    if state is None:
        if isinstance(action, InitAction):
            return FileSystemState(queue=[])

        raise InitializationActionError(action)

    match action:
        case FileSystemCopyAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    FileSystemCopyEvent(
                        sources=action.sources,
                        destination=action.destination,
                    ),
                ],
            )

        case FileSystemMoveAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    FileSystemMoveEvent(
                        sources=action.sources,
                        destination=action.destination,
                    ),
                ],
            )

        case FileSystemRemoveAction():
            return CompleteReducerResult(
                state=state,
                events=[FileSystemRemoveEvent(paths=action.paths)],
            )

        case InputDemandAction() if isinstance(
            action.description,
            PathInputDescription,
        ):
            return CompleteReducerResult(
                state=replace(state, queue=[*state.queue, action.description]),
                events=[]
                if state.queue
                else [FileSystemSelectEvent(description=action.description)],
            )

        case InputResolveAction():
            if state.queue and state.queue[0].id == action.id:
                return pop_queue(state)
            return replace(
                state,
                queue=[
                    description
                    for description in state.queue
                    if description.id != action.id
                ],
            )

        case FileSystemReportSelectionAction():
            return CompleteReducerResult(
                state=state,
                actions=[
                    InputProvideAction(
                        id=state.queue[0].id,
                        value=action.path.as_posix(),
                        result=InputResult(
                            data={'path': action.path.as_posix()},
                            files={},
                            method=InputMethod.PATH_SELECTOR,
                        ),
                    ),
                ],
            )

        case _:
            return state
