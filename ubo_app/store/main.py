# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from dataclasses import field, replace
from typing import TYPE_CHECKING, cast

from redux import (
    BaseAction,
    CompleteReducerResult,
    Immutable,
    InitAction,
    InitializationActionError,
    ReducerResult,
)
from ubo_gui.menu import Item, is_sub_menu_item, menu_items

from ubo_app.store.app import RegisterAppAction, RegisterRegularAppAction
from ubo_app.store.keypad import (
    Key,
    KeypadAction,
    KeypadEvent,
    KeypadEventPayload,
    KeypadKeyPressAction,
    KeypadKeyPressEvent,
)
from ubo_app.store.sound import (
    SoundChangeVolumeAction,
    SoundChangeVolumeActionPayload,
    SoundDevice,
)
from ubo_app.store.status_icons import IconAction

from ._menus import HOME_MENU

if TYPE_CHECKING:
    from typing_extensions import TypeAlias
    from ubo_gui.menu.types import Menu
    from ubo_gui.page import PageWidget


class MainState(Immutable):
    current_menu: Menu | None = None
    current_application: type[PageWidget] | None = None
    path: list[int] = field(default_factory=list)


class SetMenuPathActionPayload(Immutable):
    path: list[str]


class SetMenuPathAction(BaseAction):
    payload: SetMenuPathActionPayload


MainAction: TypeAlias = (
    InitAction | IconAction | KeypadAction | RegisterAppAction | SetMenuPathAction
)


def main_reducer(
    state: MainState | None,
    action: MainAction,
) -> ReducerResult[MainState, SoundChangeVolumeAction, KeypadEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return MainState(current_menu=HOME_MENU)
        raise InitializationActionError

    if isinstance(action, KeypadKeyPressAction):
        actions = []
        if action.payload.key == Key.UP and len(state.path) == 0:
            actions.append(
                SoundChangeVolumeAction(
                    payload=SoundChangeVolumeActionPayload(
                        amount=0.05,
                        device=SoundDevice.OUTPUT,
                    ),
                ),
            )
        if action.payload.key == Key.DOWN and len(state.path) == 0:
            actions.append(
                SoundChangeVolumeAction(
                    payload=SoundChangeVolumeActionPayload(
                        amount=-0.05,
                        device=SoundDevice.OUTPUT,
                    ),
                ),
            )
        return CompleteReducerResult(
            state=state,
            actions=actions,
            events=[
                KeypadKeyPressEvent(payload=KeypadEventPayload(key=action.payload.key)),
            ],
        )

    if isinstance(action, RegisterAppAction):
        # TODO(sassanh): clone the menu
        # menu = copy.deepcopy(state.current_menu)
        menu = state.current_menu

        main_menu_item: Item = menu_items(menu)[0]
        if not is_sub_menu_item(main_menu_item):
            msg = 'Main menu item is not a `SubMenuItem`'
            raise TypeError(msg)

        container_menu_item: Item
        if isinstance(action, RegisterRegularAppAction):
            container_menu_item = menu_items(main_menu_item['sub_menu'])[0]
        else:
            container_menu_item = menu_items(main_menu_item['sub_menu'])[1]

        if not is_sub_menu_item(container_menu_item):
            msg = 'Settings menu item is not a `SubMenuItem`'
            raise TypeError(msg)

        cast(list[Item], container_menu_item['sub_menu']['items']).append(
            action.payload.menu_item,
        )
        return replace(state, current_menu=menu)

    if isinstance(action, SetMenuPathAction):
        return replace(state, path=action.payload.path)

    return state
