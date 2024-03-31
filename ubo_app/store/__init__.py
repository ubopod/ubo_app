# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from threading import current_thread, main_thread
from typing import TYPE_CHECKING, Callable, Coroutine

from redux import (
    BaseCombineReducerState,
    CombineReducerAction,
    CreateStoreOptions,
    InitAction,
    Store,
    combine_reducers,
)

from ubo_app.constants import DEBUG_MODE
from ubo_app.logging import logger
from ubo_app.store.main import MainAction, MainState
from ubo_app.store.main.reducer import reducer as main_reducer
from ubo_app.store.services.camera import CameraAction, CameraEvent
from ubo_app.store.services.docker import DockerAction, DockerState
from ubo_app.store.services.ip import IpAction, IpEvent, IpState
from ubo_app.store.services.keypad import KeypadEvent
from ubo_app.store.services.notifications import NotificationsAction, NotificationsState
from ubo_app.store.services.rgb_ring import RgbRingAction
from ubo_app.store.services.sensors import SensorsAction, SensorsState
from ubo_app.store.services.sound import SoundAction, SoundState
from ubo_app.store.services.ssh import SSHAction, SSHState
from ubo_app.store.services.wifi import WiFiAction, WiFiEvent, WiFiState
from ubo_app.store.status_icons import StatusIconsAction, StatusIconsState
from ubo_app.store.status_icons.reducer import reducer as status_icons_reducer
from ubo_app.store.update_manager import UpdateManagerAction, UpdateManagerState
from ubo_app.store.update_manager.reducer import reducer as update_manager_reducer

if TYPE_CHECKING:
    from redux.basic_types import SnapshotAtom, TaskCreatorCallback

assert current_thread() is main_thread(), 'Store should be created in the main thread'  # noqa: S101


def scheduler(callback: Callable[[], None], *, interval: bool) -> None:
    from kivy.clock import Clock

    Clock.create_trigger(lambda _: callback(), 0, interval=interval)()


class RootState(BaseCombineReducerState):
    main: MainState
    status_icons: StatusIconsState
    update_manager: UpdateManagerState
    sensors: SensorsState
    ssh: SSHState
    sound: SoundState
    wifi: WiFiState
    ip: IpState
    notifications: NotificationsState
    docker: DockerState


ActionType = (
    CombineReducerAction
    | StatusIconsAction
    | UpdateManagerAction
    | MainAction
    | SensorsAction
    | SSHAction
    | SoundAction
    | CameraAction
    | WiFiAction
    | IpAction
    | NotificationsAction
    | DockerAction
    | RgbRingAction
)
EventType = KeypadEvent | CameraEvent | WiFiEvent | IpEvent

root_reducer, root_reducer_id = combine_reducers(
    state_type=RootState,
    action_type=ActionType,  # pyright: ignore [reportArgumentType]
    event_type=EventType,  # pyright: ignore [reportArgumentType]
    main=main_reducer,
    status_icons=status_icons_reducer,
    update_manager=update_manager_reducer,
)


class UboStore(Store[RootState, ActionType, EventType]):
    @classmethod
    def serialize_value(cls: type[UboStore], obj: object | type) -> SnapshotAtom:
        from ubo_gui.menu.types import ActionItem
        from ubo_gui.page import PageWidget

        if isinstance(obj, type) and issubclass(obj, PageWidget):
            file_path = sys.modules[obj.__module__].__file__
            if file_path:
                return f"""{Path(file_path).relative_to(Path().absolute()).as_posix()}:{
                obj.__name__}"""
            return f'{obj.__module__}:{obj.__name__}'
        if isinstance(obj, ActionItem):
            obj = replace(obj, action='')
        return super().serialize_value(obj)


def create_task(
    coro: Coroutine,
    *,
    callback: TaskCreatorCallback | None = None,
) -> None:
    from ubo_app.utils.async_ import create_task

    create_task(coro, callback)


store = UboStore(
    root_reducer,
    CreateStoreOptions(
        auto_init=False,
        scheduler=scheduler,
        action_middlewares=[
            lambda action: logger.debug(
                'Action dispatched',
                extra={'action': action},
            )
            or action,
        ],
        event_middlewares=[
            lambda event: logger.debug(
                'Event dispatched',
                extra={'event': event},
            )
            or event,
        ],
        task_creator=create_task,
    ),
)

autorun = store.autorun
dispatch = store.dispatch
subscribe = store.subscribe
subscribe_event = store.subscribe_event

dispatch(InitAction())

if DEBUG_MODE:
    subscribe(lambda state: logger.verbose('State updated', extra={'state': state}))

__all__ = ('autorun', 'dispatch', 'subscribe', 'subscribe_event')
