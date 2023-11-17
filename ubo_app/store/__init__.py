# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from redux import (
    BaseAction,
    BaseState,
    InitAction,
    ReducerType,
    combine_reducers,
    create_store,
)

from ubo_app.store.main import MainState, main_reducer

from .status_icons import reducer as status_icons_reducer

if TYPE_CHECKING:
    from .status_icons import StatusIconsState


@dataclass(frozen=True)
class RootState(BaseState):
    main: MainState
    status_icons: StatusIconsState


root_reducer, reducer_id = combine_reducers(
    main=main_reducer,
    status_icons=status_icons_reducer,
)
root_reducer = cast(ReducerType[RootState, BaseAction], root_reducer)


store = create_store(root_reducer)

store.dispatch(InitAction(type='INIT'))

autorun = store.autorun
dispatch = store.dispatch
subscribe = store.subscribe

__ALL__ = (autorun, dispatch, subscribe)
