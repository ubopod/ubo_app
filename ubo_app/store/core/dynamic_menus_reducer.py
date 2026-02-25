# ruff: noqa: D100, D103
from __future__ import annotations

from dataclasses import replace

from redux import CompleteReducerResult, InitAction, InitializationActionError

from ubo_app.store.core.types import (
    ClearDynamicMenuAction,
    DynamicMenuAction,
    DynamicMenuChangedEvent,
    DynamicMenuData,
    DynamicMenusState,
    UpdateDynamicMenuAction,
)


def reducer(
    state: DynamicMenusState | None,
    action: DynamicMenuAction | InitAction,
) -> DynamicMenusState | CompleteReducerResult[
    DynamicMenusState,
    DynamicMenuAction,
    DynamicMenuChangedEvent,
]:
    if state is None:
        if isinstance(action, InitAction):
            return DynamicMenusState()
        raise InitializationActionError(action)

    match action:
        case UpdateDynamicMenuAction():
            # Create the menu data from action
            menu_data = DynamicMenuData(
                menu_id=action.menu_id,
                title=action.title,
                heading=action.heading,
                sub_heading=action.sub_heading,
                items=action.items,
                placeholder=action.placeholder,
            )

            # Update the menus dict
            new_menus = {**state.menus, action.menu_id: menu_data}

            return CompleteReducerResult(
                state=replace(state, menus=new_menus, version=state.version + 1),
                events=[DynamicMenuChangedEvent(menu_id=action.menu_id)],
            )

        case ClearDynamicMenuAction():
            if action.menu_id not in state.menus:
                return state

            new_menus = {k: v for k, v in state.menus.items() if k != action.menu_id}

            return CompleteReducerResult(
                state=replace(state, menus=new_menus, version=state.version + 1),
                events=[DynamicMenuChangedEvent(menu_id=action.menu_id)],
            )

        case _:
            return state
