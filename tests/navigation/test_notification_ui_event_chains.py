"""Notification and in-place UI chains using production event handlers."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest

from ubo_app.store.core.types import (
    ApplicationScrollEvent,
    ApplicationViewData,
    MenuChooseByIndexAction,
    MenuItemData,
    MenuScrollAction,
    MenuScrollDirection,
    MenuViewData,
    NotificationViewData,
    PromptViewData,
    RenderViewData,
    StackPageIndexChangedEvent,
    StackPopAction,
    StackPopNotificationAction,
    StackPushApplicationAction,
    StackPushChatAction,
    StackPushInstructionAction,
    StackPushMenuAction,
    StackPushNotificationAction,
    StackPushPromptAction,
    StackPushRenderAction,
    UpdateApplicationKwargsAction,
    UpdatePromptAction,
    UpdateRenderPropsAction,
)
from ubo_app.store.services.notifications import (
    Notification,
    NotificationActionItem,
    NotificationDisplayType,
    NotificationsDisplayEvent,
)
from ubo_app.store.services.speech_synthesis import (
    ReadableInformation,
    SpeechSynthesisReadTextAction,
)

if TYPE_CHECKING:
    from tests.navigation.event_runner import NavigationEventRunner


def test_notification_interaction_chain(
    navigation_events: NavigationEventRunner,
) -> None:
    """Exercise paginated actions, extra information, and dismissal."""
    from ubo_app.store.core.action_registry import register_action, unregister_action

    calls: list[int] = []
    notification = Notification(
        id='interactive',
        title='Interactive',
        content='Choose an action',
        extra_information=ReadableInformation(text='More details'),
        actions=tuple(
            NotificationActionItem(
                key=f'action-{index}',
                label=f'Action {index}',
                icon=str(index),
                close_notification=False,
            )
            for index in range(4)
        ),
        display_type=NotificationDisplayType.STICKY,
    )
    action_ids = [
        f'notification:action:{notification.id}:{index}'
        for index in range(4)
    ]
    for index, action_id in enumerate(action_ids):
        register_action(action_id, lambda selected=index: calls.append(selected))

    try:
        navigation_events.set_notifications(notification)
        navigation_events.dispatch(StackPushMenuAction(menu_key='main'))
        navigation_events.dispatch(
            StackPushNotificationAction(notification_id=notification.id),
        )
        assert isinstance(navigation_events.view, NotificationViewData)
        assert navigation_events.view.total_pages == 2

        navigation_events.dispatch(MenuChooseByIndexAction(index=0))
        speech_actions = [
            cast('SpeechSynthesisReadTextAction', action)
            for action in navigation_events.dispatched_actions
            if type(action).__name__ == SpeechSynthesisReadTextAction.__name__
        ]
        assert [action.information.text for action in speech_actions] == [
            'More details',
        ]

        navigation_events.dispatch(MenuChooseByIndexAction(index=1))
        assert calls == [0]

        navigation_events.dispatch(
            MenuScrollAction(direction=MenuScrollDirection.DOWN),
        )
        assert isinstance(navigation_events.view, NotificationViewData)
        assert navigation_events.view.page_index == 1
        navigation_events.dispatch(MenuChooseByIndexAction(index=0))
        assert calls == [0, 2]

        navigation_events.dispatch(MenuChooseByIndexAction(index=2))
        assert isinstance(navigation_events.view, MenuViewData)
    finally:
        for action_id in action_ids:
            unregister_action(action_id)


@pytest.mark.asyncio
async def test_stale_flash_notification_timer_does_not_dismiss_update(
    navigation_events: NavigationEventRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ignore a stale FLASH timer but dismiss a notification still FLASH."""
    from ubo_app.utils import async_ as async_utils

    scheduled = []

    def capture_task(coroutine: object) -> None:
        scheduled.append(coroutine)

    async def no_wait(_delay: float) -> None:
        return None

    monkeypatch.setattr(async_utils, 'create_task', capture_task)
    monkeypatch.setattr(asyncio, 'sleep', no_wait)

    flash = Notification(
        id='timed',
        title='Timed',
        content='Temporary',
        display_type=NotificationDisplayType.FLASH,
        flash_time=30,
    )
    navigation_events.dispatch(StackPushMenuAction(menu_key='main'))
    navigation_events.set_notifications(flash)
    navigation_events.dispatch(StackPushNotificationAction(notification_id=flash.id))
    navigation_events.handle_event(NotificationsDisplayEvent(notification=flash))

    sticky = replace(flash, display_type=NotificationDisplayType.STICKY)
    navigation_events.set_notifications(sticky)
    await scheduled.pop(0)
    assert isinstance(navigation_events.view, NotificationViewData)

    navigation_events.set_notifications(flash)
    navigation_events.handle_event(NotificationsDisplayEvent(notification=flash))
    await scheduled.pop(0)
    assert isinstance(navigation_events.view, MenuViewData)


def test_in_place_ui_update_chain_preserves_stack_identity(
    navigation_events: NavigationEventRunner,
) -> None:
    """Update application, prompt, and render data without rebuilding stack items."""
    navigation_events.dispatch(StackPushMenuAction(menu_key='main'))
    navigation_events.dispatch(
        StackPushApplicationAction(
            application_id='test:update',
            initialization_kwargs={'step': 1, 'preserved': True},
        ),
    )
    application_item = navigation_events.state.stack[-1]
    application_depth = len(navigation_events.state.stack)
    navigation_events.dispatch(
        UpdateApplicationKwargsAction(
            application_id='test:update',
            kwargs={'step': 2},
        ),
    )
    assert navigation_events.state.stack[-1].id == application_item.id
    assert len(navigation_events.state.stack) == application_depth
    assert isinstance(navigation_events.view, ApplicationViewData)
    assert navigation_events.view.extra_data == {'step': 2, 'preserved': True}

    original_items = (
        MenuItemData(key='ok', label='OK', icon='O', action_id='test:ok'),
    )
    navigation_events.dispatch(
        StackPushPromptAction(
            title='Original',
            prompt='Waiting',
            icon='P',
            items=original_items,
        ),
    )
    prompt_item = navigation_events.state.stack[-1]
    prompt_depth = len(navigation_events.state.stack)
    navigation_events.dispatch(UpdatePromptAction(prompt='Ready'))
    assert navigation_events.state.stack[-1].id == prompt_item.id
    assert len(navigation_events.state.stack) == prompt_depth
    assert isinstance(navigation_events.view, PromptViewData)
    assert navigation_events.view.title == 'Original'
    assert navigation_events.view.prompt == 'Ready'
    assert navigation_events.view.icon == 'P'
    assert navigation_events.view.items == original_items

    navigation_events.dispatch(StackPopAction())
    navigation_events.dispatch(
        StackPushRenderAction(
            kind='text',
            title='Before',
            props={'preserved': True, 'value': 'old'},
            stream_id='stream-1',
        ),
    )
    render_item = navigation_events.state.stack[-1]
    render_depth = len(navigation_events.state.stack)
    navigation_events.dispatch(
        UpdateRenderPropsAction(
            stream_id='stream-1',
            title='After',
            props={'value': 'new'},
        ),
    )
    assert navigation_events.state.stack[-1].id == render_item.id
    assert len(navigation_events.state.stack) == render_depth
    assert isinstance(navigation_events.view, RenderViewData)
    assert navigation_events.view.title == 'After'
    assert navigation_events.view.props == {
        'preserved': True,
        'value': 'new',
    }

    navigation_events.dispatch(
        UpdateRenderPropsAction(
            stream_id='stream-1',
            next_kind='image',
            props={'source': 'frame'},
        ),
    )
    assert navigation_events.state.stack[-1].id == render_item.id
    assert isinstance(navigation_events.view, RenderViewData)
    assert navigation_events.view.kind == 'image'
    assert navigation_events.view.props == {'source': 'frame'}


def test_scroll_routing_chain_across_view_types(
    navigation_events: NavigationEventRunner,
) -> None:
    """Route scrolls to pagination, renderer events, or no-op by view type."""
    navigation_events.dispatch(StackPushMenuAction(menu_key='main'))
    navigation_events.dispatch(StackPushMenuAction(menu_key='apps'))
    navigation_events.dispatch(MenuScrollAction(direction=MenuScrollDirection.DOWN))
    assert any(
        isinstance(event, StackPageIndexChangedEvent)
        and event.page_index == 1
        for event in navigation_events.last_events
    )

    navigation_events.dispatch(
        StackPushApplicationAction(application_id='test:scroll'),
    )
    application_stack = navigation_events.state.stack
    navigation_events.dispatch(MenuScrollAction(direction=MenuScrollDirection.UP))
    assert navigation_events.state.stack == application_stack
    assert navigation_events.last_events == [ApplicationScrollEvent(direction='up')]
    navigation_events.dispatch(StackPopAction())

    navigation_events.dispatch(StackPushRenderAction(kind='text'))
    render_stack = navigation_events.state.stack
    navigation_events.dispatch(MenuScrollAction(direction=MenuScrollDirection.DOWN))
    assert navigation_events.state.stack == render_stack
    assert navigation_events.last_events == [ApplicationScrollEvent(direction='down')]
    navigation_events.dispatch(StackPopAction())

    navigation_events.dispatch(StackPushChatAction(session_id='chat-1'))
    chat_stack = navigation_events.state.stack
    navigation_events.dispatch(MenuScrollAction(direction=MenuScrollDirection.UP))
    assert navigation_events.state.stack == chat_stack
    assert navigation_events.last_events == [ApplicationScrollEvent(direction='up')]
    navigation_events.dispatch(StackPopAction())

    single_page = Notification(
        id='single-page',
        title='Single',
        content='Scrollable text',
        display_type=NotificationDisplayType.STICKY,
    )
    navigation_events.set_notifications(single_page)
    navigation_events.dispatch(
        StackPushNotificationAction(notification_id=single_page.id),
    )
    single_stack = navigation_events.state.stack
    navigation_events.dispatch(MenuScrollAction(direction=MenuScrollDirection.DOWN))
    assert navigation_events.state.stack == single_stack
    assert navigation_events.last_events == [ApplicationScrollEvent(direction='down')]
    navigation_events.dispatch(
        StackPopNotificationAction(notification_id=single_page.id),
    )

    multi_page = Notification(
        id='multi-page',
        title='Multi',
        content='Multiple action pages',
        actions=tuple(
            NotificationActionItem(label=str(index), icon=str(index))
            for index in range(4)
        ),
        display_type=NotificationDisplayType.STICKY,
    )
    navigation_events.set_notifications(multi_page)
    navigation_events.dispatch(
        StackPushNotificationAction(notification_id=multi_page.id),
    )
    navigation_events.dispatch(MenuScrollAction(direction=MenuScrollDirection.DOWN))
    assert isinstance(navigation_events.view, NotificationViewData)
    assert navigation_events.view.page_index == 1
    assert navigation_events.last_events == [
        StackPageIndexChangedEvent(page_index=1),
    ]
    navigation_events.dispatch(
        StackPopNotificationAction(notification_id=multi_page.id),
    )

    navigation_events.dispatch(
        StackPushPromptAction(title='Prompt', prompt='No scrolling'),
    )
    prompt_stack = navigation_events.state.stack
    navigation_events.dispatch(MenuScrollAction(direction=MenuScrollDirection.DOWN))
    assert navigation_events.state.stack == prompt_stack
    assert navigation_events.last_events == []
    navigation_events.dispatch(StackPopAction())

    navigation_events.dispatch(
        StackPushInstructionAction(title='Instruction', instruction='Wait'),
    )
    instruction_stack = navigation_events.state.stack
    navigation_events.dispatch(MenuScrollAction(direction=MenuScrollDirection.UP))
    assert navigation_events.state.stack == instruction_stack
    assert navigation_events.last_events == []
