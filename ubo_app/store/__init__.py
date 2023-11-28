# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from typing import TYPE_CHECKING

from redux import (
    BaseCombineReducerState,
    CombineReducerAction,
    InitAction,
    combine_reducers,
    create_store,
)

from ubo_app.store.keypad import KeyEvent
from ubo_app.store.main import MainAction, MainState, main_reducer
from ubo_app.store.sound import SoundAction, SoundState

from .status_icons import IconAction
from .status_icons import reducer as status_icons_reducer

if TYPE_CHECKING:
    from .status_icons import StatusIconsState


class RootState(BaseCombineReducerState):
    main: MainState
    sound: SoundState
    status_icons: StatusIconsState


root_reducer, root_reducer_id = combine_reducers(
    state_type=RootState,
    action_type=MainAction | SoundAction | IconAction | CombineReducerAction,
    event_type=KeyEvent,
    main=main_reducer,
    status_icons=status_icons_reducer,
)


store = create_store(root_reducer)

store.dispatch(InitAction(type='INIT'))

autorun = store.autorun


def dispatch(items: ActionType | EventType | list[ActionType | EventType]) -> None:
    from kivy.clock import Clock

    logger.debug(items)
    Clock.schedule_once(lambda _: store.dispatch(items), -1)


subscribe = store.subscribe
subscribe_event = store.subscribe_event

__ALL__ = (autorun, dispatch, subscribe)
