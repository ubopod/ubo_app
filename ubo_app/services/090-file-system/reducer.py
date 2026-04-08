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

from ubo_app.store.core.types import StackPopAction
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
    FileSystemSelectorCleanupEvent,
    FileSystemSelectorPushedAction,
    FileSystemState,
)
from ubo_app.store.services.notifications import NotificationsClearByIdAction

DispatchAction = NotificationsClearByIdAction | InputProvideAction | StackPopAction


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

    if state.queue:
        actions += [
            NotificationsClearByIdAction(
                id=SELECTOR_APPLICATION_ID.format(id=state.queue[0].id),
            ),
        ]

    if state.selector_depth > 0:
        actions.append(StackPopAction(count=state.selector_depth))
        events.append(FileSystemSelectorCleanupEvent())

    _, *queue = state.queue
    if queue:
        events.append(FileSystemSelectEvent(description=queue[0]))
    return CompleteReducerResult(
        state=replace(state, queue=queue, selector_depth=0),
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

        case FileSystemSelectorPushedAction():
            return replace(state, selector_depth=state.selector_depth + 1)

        case InputDemandAction() if isinstance(
            action.description,
            PathInputDescription,
        ):
            return CompleteReducerResult(
                state=replace(
                    state,
                    queue=[*state.queue, action.description],
                    selector_depth=0,
                ),
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
            if not state.queue:
                return state
            actions: list[DispatchAction] = [
                InputProvideAction(
                    id=state.queue[0].id,
                    value=action.path,
                    result=InputResult(
                        data={'path': action.path},
                        files={},
                        method=InputMethod.PATH_SELECTOR,
                    ),
                ),
            ]
            selection_events: list[FileSystemEvent] = [
                FileSystemSelectorCleanupEvent(),
            ]
            if state.selector_depth > 0:
                actions.append(StackPopAction(count=state.selector_depth))
            return CompleteReducerResult(
                state=replace(state, selector_depth=0),
                actions=actions,
                events=selection_events,
            )

        case _:
            return state
