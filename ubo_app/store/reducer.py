# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from dataclasses import replace
from typing import Sequence, cast

import semver
from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)
from ubo_gui.constants import SECONDARY_COLOR
from ubo_gui.menu.types import Menu, SubMenuItem

from ubo_app.store.main import (
    InitEvent,
    MainAction,
    MainState,
    PowerOffAction,
    PowerOffEvent,
    RegisterAppAction,
    RegisterRegularAppAction,
    SetMenuPathAction,
)
from ubo_app.store.services.keypad import (
    Key,
    KeypadEvent,
    KeypadKeyPressAction,
    KeypadKeyPressEvent,
)
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.sound import SoundChangeVolumeAction, SoundDevice
from ubo_app.store.update_manager_types import (
    UPDATE_MANAGER_NOTIFICATION_ID,
    CheckVersionEvent,
    SetLatestVersionAction,
    SetUpdateStatusAction,
    UpdateStatus,
    UpdateVersionEvent,
)

ABOUT_MENU_PATH = ['Dashboard', 'Main', 'About']


def reducer(  # noqa: C901, PLR0912
    state: MainState | None,
    action: MainAction,
) -> ReducerResult[
    MainState,
    SetUpdateStatusAction | NotificationsAddAction | SoundChangeVolumeAction,
    KeypadEvent | InitEvent | PowerOffEvent,
]:
    if state is None:
        if isinstance(action, InitAction):
            from ._menus import HOME_MENU

            return CompleteReducerResult(
                state=MainState(menu=HOME_MENU),
                events=[InitEvent()],
            )
        raise InitializationActionError(action)

    if isinstance(action, KeypadKeyPressAction):
        actions = []
        if action.key == Key.UP and len(state.path) == 0:
            actions.append(
                SoundChangeVolumeAction(
                    amount=0.05,
                    device=SoundDevice.OUTPUT,
                ),
            )
        if action.key == Key.DOWN and len(state.path) == 0:
            actions.append(
                SoundChangeVolumeAction(
                    amount=-0.05,
                    device=SoundDevice.OUTPUT,
                ),
            )
        return CompleteReducerResult(
            state=state,
            actions=actions,
            events=[
                KeypadKeyPressEvent(key=action.key),
            ],
        )

    if isinstance(action, RegisterAppAction):
        from ubo_gui.menu import Item, menu_items

        menu = state.menu
        parent_index = 0 if isinstance(action, RegisterRegularAppAction) else 1

        if not menu:
            return state

        root_menu_items = menu_items(menu)

        main_menu_item: Item = root_menu_items[0]
        if not isinstance(main_menu_item, SubMenuItem):
            msg = 'Main menu item is not a `SubMenuItem`'
            raise TypeError(msg)

        main_menu_items = menu_items(cast(Menu, main_menu_item.sub_menu))

        desired_menu_item = main_menu_items[parent_index]
        if not isinstance(desired_menu_item, SubMenuItem):
            menu_title = (
                'Applications'
                if isinstance(action, RegisterRegularAppAction)
                else 'Settings'
            )
            msg = f'{menu_title} menu item is not a `SubMenuItem`'
            raise TypeError(msg)

        new_items = [
            *cast(Sequence[Item], cast(Menu, desired_menu_item.sub_menu).items),
            action.menu_item,
        ]
        desired_menu_item = replace(
            desired_menu_item,
            sub_menu=replace(
                cast(Menu, desired_menu_item.sub_menu),
                items=new_items,
            ),
        )
        main_menu_item = replace(
            main_menu_item,
            sub_menu=replace(
                cast(Menu, main_menu_item.sub_menu),
                items=[
                    desired_menu_item if index == parent_index else item
                    for index, item in enumerate(main_menu_items)
                ],
            ),
        )

        return replace(
            state,
            menu=replace(
                menu,
                items=[
                    main_menu_item if index == 0 else item
                    for index, item in enumerate(root_menu_items)
                ],
            ),
        )

    if isinstance(action, SetMenuPathAction):
        new_state = replace(state, path=action.path)

        if (
            action.path == ABOUT_MENU_PATH
            and state.path[:3] != ABOUT_MENU_PATH
            and state.version.update_status
            in [
                UpdateStatus.FAILED_TO_CHECK,
                UpdateStatus.UP_TO_DATE,
                UpdateStatus.OUTDATED,
            ]
        ):
            return CompleteReducerResult(
                state=new_state,
                actions=[
                    SetUpdateStatusAction(status=UpdateStatus.CHECKING),
                ],
            )
        return new_state

    if isinstance(action, SetLatestVersionAction):
        state = replace(
            state,
            version=replace(
                state.version,
                current_version=action.current_version,
                latest_version=action.latest_version,
            ),
        )
        if semver.compare(action.latest_version, action.current_version) != 0:
            is_in_about_menu = state.path[:3] == ABOUT_MENU_PATH
            return CompleteReducerResult(
                state=state,
                actions=[
                    SetUpdateStatusAction(status=UpdateStatus.OUTDATED),
                    NotificationsAddAction(
                        notification=Notification(
                            id=UPDATE_MANAGER_NOTIFICATION_ID,
                            title='Update available!',
                            content=f"""Ubo v{action.latest_version
                            } is available. Go to the About menu to update.""",
                            display_type=NotificationDisplayType.BACKGROUND
                            if is_in_about_menu
                            else NotificationDisplayType.FLASH,
                            color=SECONDARY_COLOR,
                            icon='system_update',
                            chime=Chime.DONE,
                        ),
                    ),
                ],
            )
        return CompleteReducerResult(
            state=state,
            actions=[
                SetUpdateStatusAction(status=UpdateStatus.UP_TO_DATE),
            ],
        )

    if isinstance(action, SetUpdateStatusAction):
        events = []
        if action.status == UpdateStatus.CHECKING:
            events.append(CheckVersionEvent())
        elif action.status == UpdateStatus.UPDATING:
            events.append(UpdateVersionEvent())

        return CompleteReducerResult(
            state=replace(
                state,
                version=replace(
                    state.version,
                    update_status=action.status,
                ),
            ),
            events=events,
        )

    if isinstance(action, PowerOffAction):
        return CompleteReducerResult(
            state=state,
            events=[PowerOffEvent()],
        )

    return state
