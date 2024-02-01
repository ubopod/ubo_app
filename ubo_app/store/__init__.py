# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from typing import Callable

from kivy.base import Clock
from redux import (
    BaseCombineReducerState,
    CombineReducerAction,
    CreateStoreOptions,
    combine_reducers,
    create_store,
)

from ubo_app.constants import DEBUG_MODE
from ubo_app.logging import logger
from ubo_app.store.main import MainAction, MainState
from ubo_app.store.main.reducer import reducer as main_reducer
from ubo_app.store.services.camera import CameraAction, CameraEvent
from ubo_app.store.services.docker import DockerEvent, DockerState
from ubo_app.store.services.ip import IpAction, IpEvent, IpState
from ubo_app.store.services.keypad import KeypadEvent
from ubo_app.store.services.notifications import NotificationsAction, NotificationsState
from ubo_app.store.services.sensors import SensorsAction, SensorsState
from ubo_app.store.services.sound import SoundAction, SoundState
from ubo_app.store.services.wifi import WiFiAction, WiFiEvent, WiFiState
from ubo_app.store.status_icons import StatusIconsAction, StatusIconsState
from ubo_app.store.status_icons.reducer import reducer as status_icons_reducer
from ubo_app.store.update_manager import UpdateManagerAction, UpdateManagerState
from ubo_app.store.update_manager.reducer import reducer as update_manager_reducer


class RootState(BaseCombineReducerState):
    main: MainState
    status_icons: StatusIconsState
    update_manager: UpdateManagerState
    sensors: SensorsState
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
    | SoundAction
    | CameraAction
    | WiFiAction
    | IpAction
    | NotificationsAction
    | DockerEvent
)
EventType = KeypadEvent | CameraEvent | WiFiEvent | IpEvent

root_reducer, root_reducer_id = combine_reducers(
    state_type=RootState,
    action_type=ActionType,
    event_type=EventType,
    main=main_reducer,
    status_icons=status_icons_reducer,
    update_manager=update_manager_reducer,
)


def scheduler(callback: Callable[[], None], *, interval: bool) -> None:
    Clock.create_trigger(lambda _: callback(), 0, interval=interval)()


store = create_store(
    root_reducer,
    CreateStoreOptions(
        auto_init=True,
        scheduler=scheduler,
        action_middleware=lambda action: logger.debug(
            'Action dispatched',
            extra={'action': action},
        ),
        event_middleware=lambda event: logger.debug(
            'Event dispatched',
            extra={'event': event},
        ),
    ),
)

autorun = store.autorun
dispatch = store.dispatch
subscribe = store.subscribe
subscribe_event = store.subscribe_event

if DEBUG_MODE:
    subscribe(lambda state: logger.verbose('State updated', extra={'state': state}))

__ALL__ = (autorun, dispatch, subscribe, subscribe_event)
