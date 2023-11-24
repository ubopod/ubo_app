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
    action_type=MainAction | SoundAction | IconAction | CombineReducerAction,
    state_type=RootState,
    main=main_reducer,
    status_icons=status_icons_reducer,
)


store = create_store(root_reducer)

store.dispatch(InitAction(type='INIT'))

autorun = store.autorun
dispatch = store.dispatch
subscribe = store.subscribe

__ALL__ = (autorun, dispatch, subscribe)
