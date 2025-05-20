# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, cast

from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)
from ubo_gui.menu.types import Item, Menu, SubMenuItem, menu_items

from ubo_app.store.core.menus import HOME_MENU
from ubo_app.store.core.types import (
    CloseApplicationAction,
    CloseApplicationEvent,
    DeregisterRegularAppAction,
    InitEvent,
    MainAction,
    MainEvent,
    MainState,
    MenuChooseByIconAction,
    MenuChooseByIconEvent,
    MenuChooseByIndexAction,
    MenuChooseByIndexEvent,
    MenuChooseByLabelAction,
    MenuChooseByLabelEvent,
    MenuGoBackAction,
    MenuGoBackEvent,
    MenuGoHomeAction,
    MenuGoHomeEvent,
    MenuScrollAction,
    MenuScrollEvent,
    OpenApplicationAction,
    OpenApplicationEvent,
    PowerOffAction,
    PowerOffEvent,
    RebootAction,
    RebootEvent,
    RegisterRegularAppAction,
    RegisterSettingAppAction,
    ReplayRecordedSequenceAction,
    ReplayRecordedSequenceEvent,
    ReportReplayingDoneAction,
    SetAreEnclosuresVisibleAction,
    SetMenuPathAction,
    StoreRecordedSequenceEvent,
    ToggleRecordingAction,
)
from ubo_app.store.settings.types import SettingsServiceSetStatusAction

if TYPE_CHECKING:
    from collections.abc import Sequence


def find_sub_menu_item(items: Sequence[Item], key: str) -> SubMenuItem:
    item = next((item for item in items if item.key == key), None)
    if not isinstance(item, SubMenuItem):
        msg = f'{key.capitalize()} menu item is not a `SubMenuItem`'
        raise TypeError(msg)
    return item


def reducer(
    state: MainState | None,
    action: MainAction,
) -> ReducerResult[MainState, None, InitEvent | MainEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return MainState(menu=HOME_MENU)
        raise InitializationActionError(action)

    if state.is_recording:
        state = replace(
            state,
            recorded_sequence=[
                *state.recorded_sequence,
                action,
            ],
        )

    if isinstance(action, MenuGoBackAction):
        return CompleteReducerResult(
            state=state,
            events=[MenuGoBackEvent()],
        )

    if isinstance(action, MenuGoHomeAction):
        return CompleteReducerResult(
            state=state,
            events=[MenuGoHomeEvent()],
        )

    if isinstance(action, MenuChooseByIconAction):
        return CompleteReducerResult(
            state=state,
            events=[MenuChooseByIconEvent(icon=action.icon)],
        )

    if isinstance(action, MenuChooseByLabelAction):
        return CompleteReducerResult(
            state=state,
            events=[MenuChooseByLabelEvent(label=action.label)],
        )

    if isinstance(action, MenuChooseByIndexAction):
        return CompleteReducerResult(
            state=state,
            events=[MenuChooseByIndexEvent(index=action.index)],
        )
    if isinstance(action, MenuScrollAction):
        return CompleteReducerResult(
            state=state,
            events=[MenuScrollEvent(direction=action.direction)],
        )

    if isinstance(action, OpenApplicationAction):
        return CompleteReducerResult(
            state=state,
            events=[
                OpenApplicationEvent(
                    application_id=action.application_id,
                    initialization_args=action.initialization_args,
                    initialization_kwargs=action.initialization_kwargs,
                ),
            ],
        )

    if isinstance(action, CloseApplicationAction):
        return CompleteReducerResult(
            state=state,
            events=[
                CloseApplicationEvent(
                    application_instance_id=action.application_instance_id,
                ),
            ],
        )

    if isinstance(action, ToggleRecordingAction) and not state.is_replaying:
        return CompleteReducerResult(
            state=replace(
                state,
                is_recording=not state.is_recording,
                recorded_sequence=[],
            ),
            events=[
                StoreRecordedSequenceEvent(recorded_sequence=state.recorded_sequence),
            ]
            if state.is_recording
            else [],
        )

    if (
        isinstance(action, ReplayRecordedSequenceAction)
        and not state.is_recording
        and not state.is_replaying
    ):
        return CompleteReducerResult(
            state=replace(state, is_replaying=True),
            events=[ReplayRecordedSequenceEvent()],
        )

    if isinstance(action, ReportReplayingDoneAction):
        return replace(state, is_replaying=False)

    if isinstance(action, RegisterSettingAppAction):
        menu = state.menu
        if not menu or not action.service:
            return state
        root_menu_items = menu_items(menu)
        main_menu_item = find_sub_menu_item(root_menu_items, 'main')
        main_menu_items = menu_items(cast('Menu', main_menu_item.sub_menu))
        settings_menu_item = find_sub_menu_item(main_menu_items, 'settings')
        settings_menu_items = menu_items(cast('Menu', settings_menu_item.sub_menu))

        category_menu_item = cast(
            'SubMenuItem',
            next(item for item in settings_menu_items if item.label == action.category),
        )

        key = f'{action.service}:'
        if action.key is not None:
            key += action.key

        priorities = {
            **state.settings_items_priorities,
            key: action.priority,
        }

        def sort_key(item: Item) -> tuple[int, str]:
            key = item.key or (item.label() if callable(item.label) else item.label)
            return (-(priorities.get(key, 0) or 0), key)

        if any(
            item.key == key
            for item in cast(
                'Sequence[Item]',
                cast('Menu', category_menu_item.sub_menu).items,
            )
        ):
            msg = f"""Settings application with key "{key}", in category \
"{category_menu_item.label}", already exists. Consider providing a unique `key` field \
for the `RegisterSettingAppAction` instance."""
            raise ValueError(msg)

        menu_item = replace(action.menu_item, key=key)
        new_items = sorted(
            [
                *cast(
                    'Sequence[Item]',
                    cast('Menu', category_menu_item.sub_menu).items,
                ),
                menu_item,
            ],
            key=sort_key,
        )

        new_category_menu_item = replace(
            category_menu_item,
            sub_menu=replace(
                cast('Menu', category_menu_item.sub_menu),
                items=new_items,
            ),
        )

        new_settings_menu_item = replace(
            settings_menu_item,
            sub_menu=replace(
                cast('Menu', settings_menu_item.sub_menu),
                items=[
                    new_category_menu_item if item == category_menu_item else item
                    for item in settings_menu_items
                ],
            ),
        )

        new_main_menu_item = replace(
            main_menu_item,
            sub_menu=replace(
                cast('Menu', main_menu_item.sub_menu),
                items=[
                    new_settings_menu_item if item == settings_menu_item else item
                    for item in main_menu_items
                ],
            ),
        )

        return replace(
            state,
            settings_items_priorities=priorities,
            menu=replace(
                menu,
                items=[
                    new_main_menu_item if item == main_menu_item else item
                    for item in root_menu_items
                ],
            ),
        )

    if isinstance(action, RegisterRegularAppAction):
        menu = state.menu
        if not menu or not action.service:
            return state
        root_menu_items = menu_items(menu)
        main_menu_item = find_sub_menu_item(root_menu_items, 'main')
        main_menu_items = menu_items(cast('Menu', main_menu_item.sub_menu))
        apps_menu_item = find_sub_menu_item(main_menu_items, 'apps')
        apps_menu_items = menu_items(cast('Menu', apps_menu_item.sub_menu))

        key = f'{action.service}:'
        if action.key is not None:
            key += action.key
        if any(item.key == key for item in apps_menu_items):
            msg = f"""Regular application with key "{key}", already exists. Consider \
providing a unique `key` field for the `RegisterRegularAppAction` instance."""
            raise ValueError(msg)

        priorities = {
            **state.apps_items_priorities,
            key: action.priority,
        }

        def sort_key(item: Item) -> tuple[int, str]:
            key = item.key or (item.label() if callable(item.label) else item.label)
            return (-(priorities.get(key, 0) or 0), key)

        menu_item = replace(action.menu_item, key=key)
        new_items = sorted(
            [
                *cast('Sequence[Item]', apps_menu_items),
                menu_item,
            ],
            key=sort_key,
        )

        apps_menu_item = replace(
            apps_menu_item,
            sub_menu=replace(
                cast('Menu', apps_menu_item.sub_menu),
                items=new_items,
            ),
        )

        main_menu_item = replace(
            main_menu_item,
            sub_menu=replace(
                cast('Menu', main_menu_item.sub_menu),
                items=[
                    apps_menu_item if item.key == 'apps' else item
                    for item in main_menu_items
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

    if isinstance(action, DeregisterRegularAppAction):
        if action.service is None:
            return state
        key = f'{action.service}:'
        if action.key is not None:
            key += action.key

        menu = state.menu
        if not menu:
            return state
        root_menu_items = menu_items(menu)
        main_menu_item = find_sub_menu_item(root_menu_items, 'main')
        main_menu_items = menu_items(cast('Menu', main_menu_item.sub_menu))
        apps_menu_item = find_sub_menu_item(main_menu_items, 'apps')
        apps_menu_items = menu_items(cast('Menu', apps_menu_item.sub_menu))

        new_items = [item for item in apps_menu_items if item.key != key]

        new_apps_menu_item = replace(
            apps_menu_item,
            sub_menu=replace(
                cast('Menu', apps_menu_item.sub_menu),
                items=new_items,
            ),
        )

        new_main_menu_item = replace(
            main_menu_item,
            sub_menu=replace(
                cast('Menu', main_menu_item.sub_menu),
                items=[
                    new_apps_menu_item if item == apps_menu_item else item
                    for item in main_menu_items
                ],
            ),
        )

        events: list[MenuGoBackEvent] = []

        if state.path[:3] == ['main', 'apps', key]:
            events = [MenuGoBackEvent()] * (len(state.path) - 2)

        return CompleteReducerResult(
            state=replace(
                state,
                menu=replace(
                    menu,
                    items=[
                        new_main_menu_item if item == main_menu_item else item
                        for item in root_menu_items
                    ],
                ),
            ),
            events=events,
        )

    if isinstance(action, SetMenuPathAction):
        return replace(state, path=action.path, depth=action.depth)

    if isinstance(action, SetAreEnclosuresVisibleAction):
        return replace(
            state,
            is_header_visible=action.is_header_visible,
            is_footer_visible=action.is_footer_visible,
        )

    if isinstance(action, PowerOffAction):
        return CompleteReducerResult(
            state=state,
            events=[PowerOffEvent()],
        )

    if isinstance(action, RebootAction):
        return CompleteReducerResult(
            state=state,
            events=[RebootEvent()],
        )

    if isinstance(action, SettingsServiceSetStatusAction):  # noqa: SIM102
        if action.is_active is False:
            menu = state.menu
            if not menu:
                return state
            root_menu_items = menu_items(menu)
            main_menu_item = find_sub_menu_item(root_menu_items, 'main')
            main_menu_items = menu_items(cast('Menu', main_menu_item.sub_menu))
            apps_menu_item = find_sub_menu_item(main_menu_items, 'apps')
            apps_menu_items = menu_items(cast('Menu', apps_menu_item.sub_menu))
            settings_menu_item = find_sub_menu_item(main_menu_items, 'settings')
            settings_menu_items = menu_items(cast('Menu', settings_menu_item.sub_menu))

            new_apps_menu_item = replace(
                apps_menu_item,
                sub_menu=replace(
                    cast('Menu', apps_menu_item.sub_menu),
                    items=[
                        item
                        for item in apps_menu_items
                        if item.key is None
                        or not item.key.startswith(f'{action.service_id}:')
                    ],
                ),
            )

            new_settings_menu_item = replace(
                settings_menu_item,
                sub_menu=replace(
                    cast('Menu', settings_menu_item.sub_menu),
                    items=[
                        replace(
                            category_menu_item,
                            sub_menu=replace(
                                cast('Menu', category_menu_item.sub_menu),
                                items=[
                                    item
                                    for item in menu_items(
                                        cast('Menu', category_menu_item.sub_menu),
                                    )
                                    if item.key is None
                                    or not item.key.startswith(f'{action.service_id}:')
                                ],
                            ),
                        )
                        if isinstance(category_menu_item, SubMenuItem)
                        else category_menu_item
                        for category_menu_item in settings_menu_items
                    ],
                ),
            )

            new_main_menu_item = replace(
                main_menu_item,
                sub_menu=replace(
                    cast('Menu', main_menu_item.sub_menu),
                    items=[
                        new_apps_menu_item
                        if item == apps_menu_item
                        else new_settings_menu_item
                        if item == settings_menu_item
                        else item
                        for item in main_menu_items
                    ],
                ),
            )

            events: list[MenuGoBackEvent] = []

            # Exit open menus of the deregistered app
            if (
                state.path[:2] == ['main', 'apps']
                and len(state.path) > 2  # noqa: PLR2004
                and state.path[2].startswith(
                    f'{action.service_id}:',
                )
            ):
                events = [MenuGoBackEvent()] * (len(state.path) - 2)
            if (
                state.path[:2] == ['main', 'settings']
                and len(state.path) > 3  # noqa: PLR2004
                and state.path[3].startswith(
                    f'{action.service_id}:',
                )
            ):
                events = [MenuGoBackEvent()] * (len(state.path) - 3)

            return CompleteReducerResult(
                state=replace(
                    state,
                    menu=replace(
                        menu,
                        items=[
                            new_main_menu_item if item == main_menu_item else item
                            for item in root_menu_items
                        ],
                    ),
                ),
                events=events,
            )

    return state
