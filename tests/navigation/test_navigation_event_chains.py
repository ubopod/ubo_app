"""Navigation chains that exercise the production UI event handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.store.core.types import (
    ApplicationViewData,
    CloseApplicationAction,
    DynamicMenuData,
    HomeViewData,
    MenuChooseByIndexAction,
    MenuGoBackAction,
    MenuGoHomeAction,
    MenuItemData,
    MenuScrollAction,
    MenuScrollDirection,
    MenuViewData,
    NotificationViewData,
    PromptViewData,
    StackPopAction,
    StackPopItemAction,
    StackPushApplicationAction,
    StackPushMenuAction,
    StackPushNotificationAction,
    StackPushPromptAction,
)
from ubo_app.store.services.notifications import (
    Notification,
    NotificationDisplayType,
)

if TYPE_CHECKING:
    from tests.navigation.event_runner import NavigationEventRunner


def test_full_production_navigation_event_chain(
    navigation_events: NavigationEventRunner,
) -> None:
    """Drive index events through handlers, pagination, Back, and Home."""
    navigation_events.dispatch(MenuChooseByIndexAction(index=0))
    assert navigation_events.state.path == ('main',)
    assert isinstance(navigation_events.view, MenuViewData)
    assert navigation_events.view.title == 'Main'

    navigation_events.dispatch(MenuChooseByIndexAction(index=0))
    assert navigation_events.state.path == ('main', 'apps')
    assert isinstance(navigation_events.view, MenuViewData)
    assert navigation_events.view.title == 'Apps'

    navigation_events.dispatch(MenuScrollAction(direction=MenuScrollDirection.DOWN))
    navigation_events.dispatch(MenuScrollAction(direction=MenuScrollDirection.DOWN))
    assert isinstance(navigation_events.view, MenuViewData)
    assert navigation_events.view.page_index == 2

    navigation_events.dispatch(MenuChooseByIndexAction(index=0))
    assert navigation_events.state.path == ('main', 'apps', 'app6')

    navigation_events.dispatch(MenuGoBackAction())
    assert navigation_events.state.path == ('main', 'apps')

    navigation_events.dispatch(MenuGoHomeAction())
    assert navigation_events.state.path == ()
    assert isinstance(navigation_events.view, HomeViewData)


def test_headed_menu_index_mapping_across_pages(
    navigation_events: NavigationEventRunner,
) -> None:
    """Reserve heading slots on page zero and map later pages correctly."""
    navigation_events.dynamic_menus['test:headed'] = DynamicMenuData(
        menu_id='test:headed',
        title='Headed',
        heading='Heading',
        sub_heading='Subheading',
        items=tuple(
            MenuItemData(
                key=f'headed-{index}',
                label=f'Item {index}',
                icon=str(index),
                action_id=f'menu:select:headed-{index}',
            )
            for index in range(4)
        ),
    )
    navigation_events.path_mappings[('main', 'headed')] = 'test:headed'
    navigation_events.dispatch(StackPushMenuAction(menu_key='main'))
    navigation_events.dispatch(StackPushMenuAction(menu_key='headed'))

    assert isinstance(navigation_events.view, MenuViewData)
    assert navigation_events.view.total_pages == 2

    initial_stack = navigation_events.state.stack
    navigation_events.dispatch(MenuChooseByIndexAction(index=0))
    navigation_events.dispatch(MenuChooseByIndexAction(index=1))
    assert navigation_events.state.stack == initial_stack

    navigation_events.dispatch(MenuChooseByIndexAction(index=2))
    assert navigation_events.state.path[-1] == 'headed-0'
    navigation_events.dispatch(StackPopAction())

    navigation_events.dispatch(MenuScrollAction(direction=MenuScrollDirection.DOWN))
    assert isinstance(navigation_events.view, MenuViewData)
    assert navigation_events.view.page_index == 1
    navigation_events.dispatch(MenuChooseByIndexAction(index=0))
    assert navigation_events.state.path[-1] == 'headed-1'


def test_overlay_routing_and_view_restoration_chain(
    navigation_events: NavigationEventRunner,
) -> None:
    """Route input to the visible overlay and restore every underlying view."""
    sticky = Notification(
        id='visible',
        title='Visible',
        content='Visible notification',
        display_type=NotificationDisplayType.STICKY,
    )
    background = Notification(
        id='background',
        title='Background',
        content='Hidden notification',
        display_type=NotificationDisplayType.BACKGROUND,
    )
    navigation_events.set_notifications(sticky, background)
    navigation_events.dispatch(StackPushMenuAction(menu_key='main'))
    navigation_events.dispatch(
        StackPushApplicationAction(application_id='test:application'),
    )
    application_id = navigation_events.state.stack[-1].id
    navigation_events.dispatch(
        StackPushPromptAction(title='Confirm', prompt='Continue?'),
    )
    prompt_id = navigation_events.state.stack[-1].id
    navigation_events.dispatch(
        StackPushNotificationAction(notification_id=sticky.id),
    )
    navigation_events.dispatch(
        StackPushNotificationAction(notification_id=background.id),
    )

    assert isinstance(navigation_events.view, NotificationViewData)
    assert navigation_events.view.notification_id == sticky.id
    navigation_events.dispatch(MenuChooseByIndexAction(index=2))
    assert isinstance(navigation_events.view, PromptViewData)

    navigation_events.dispatch(StackPopItemAction(item_id=prompt_id))
    assert isinstance(navigation_events.view, ApplicationViewData)
    navigation_events.dispatch(
        CloseApplicationAction(application_instance_id=application_id),
    )
    assert isinstance(navigation_events.view, MenuViewData)

    navigation_events.dispatch(MenuChooseByIndexAction(index=0))
    assert navigation_events.state.path == ('main', 'apps')


def test_prompt_and_application_button_selection_chain(
    navigation_events: NavigationEventRunner,
) -> None:
    """Map application and bottom-aligned prompt buttons to registered actions."""
    from ubo_app.store.core.action_registry import register_action, unregister_action

    calls: list[str] = []
    navigation_events.dispatch(StackPushMenuAction(menu_key='main'))
    navigation_events.dispatch(
        StackPushApplicationAction(application_id='test:buttons'),
    )
    application_instance_id = navigation_events.state.stack[-1].id

    def open_prompt() -> None:
        calls.append('application:1')
        navigation_events.dispatch(
            StackPushPromptAction(
                title='Confirm',
                prompt='Proceed?',
                items=(
                    MenuItemData(
                        key='confirm',
                        label='Confirm',
                        icon='Y',
                        action_id='test:prompt:confirm',
                    ),
                    MenuItemData(
                        key='cancel',
                        label='Cancel',
                        icon='N',
                        action_id='test:prompt:cancel',
                    ),
                ),
            ),
        )

    def confirm_prompt() -> None:
        calls.append('prompt:confirm')
        navigation_events.dispatch(StackPopAction())

    def close_application() -> None:
        calls.append('application:2')
        navigation_events.dispatch(
            CloseApplicationAction(
                application_instance_id=application_instance_id,
            ),
        )

    handlers = {
        'app-button:test:buttons:1': open_prompt,
        'test:prompt:confirm': confirm_prompt,
        'test:prompt:cancel': lambda: calls.append('prompt:cancel'),
        'app-button:test:buttons:2': close_application,
    }
    for action_id, handler in handlers.items():
        register_action(action_id, handler)

    try:
        navigation_events.dispatch(MenuChooseByIndexAction(index=1))
        assert isinstance(navigation_events.view, PromptViewData)

        navigation_events.dispatch(MenuChooseByIndexAction(index=0))
        assert calls == ['application:1']
        navigation_events.dispatch(MenuChooseByIndexAction(index=1))
        assert calls == ['application:1', 'prompt:confirm']
        assert isinstance(navigation_events.view, ApplicationViewData)

        navigation_events.dispatch(MenuChooseByIndexAction(index=2))
        assert calls == ['application:1', 'prompt:confirm', 'application:2']
        assert isinstance(navigation_events.view, MenuViewData)
    finally:
        for action_id in handlers:
            unregister_action(action_id)
