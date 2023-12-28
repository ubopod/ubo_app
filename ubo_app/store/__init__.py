# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from headless_kivy_pi import HeadlessWidget
from kivy.base import Clock
from redux import (
    BaseCombineReducerState,
    CombineReducerAction,
    CreateStoreOptions,
    combine_reducers,
    create_store,
)

from ubo_app.logging import logger
from ubo_app.store.camera import CameraAction, CameraEvent
from ubo_app.store.ip import IpAction, IpEvent, IpState
from ubo_app.store.keypad import KeypadEvent
from ubo_app.store.main import MainAction, MainState, main_reducer
from ubo_app.store.sound import SoundAction, SoundState
from ubo_app.store.wifi import WiFiAction, WiFiEvent, WiFiState

from .status_icons import reducer as status_icons_reducer

if TYPE_CHECKING:
    from .status_icons import StatusIconsState


class RootState(BaseCombineReducerState):
    main: MainState
    status_icons: StatusIconsState
    sound: SoundState
    wifi: WiFiState
    ip: IpState


ActionType = (
    MainAction
    | CombineReducerAction
    | SoundAction
    | CameraAction
    | WiFiAction
    | IpAction
)
EventType = KeypadEvent | CameraEvent | WiFiEvent | IpEvent

root_reducer, root_reducer_id = combine_reducers(
    state_type=RootState,
    action_type=ActionType,
    event_type=EventType,
    main=main_reducer,
    status_icons=status_icons_reducer,
)


def scheduler(main_loop_callback: Callable[[], None]) -> None:
    Clock.create_trigger(
        lambda _: main_loop_callback(),
        0,
        interval=True,
    )()


store = create_store(
    root_reducer,
    CreateStoreOptions(
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

subscribe(lambda _: HeadlessWidget.render())

__ALL__ = (autorun, dispatch, subscribe)
