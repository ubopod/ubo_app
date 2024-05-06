# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import functools
import re
import weakref
from dataclasses import replace
from typing import TYPE_CHECKING

from debouncer import DebounceOptions, debounce
from kivy.clock import Clock, mainthread
from ubo_gui.app import UboApp
from ubo_gui.constants import DANGER_COLOR, INFO_COLOR
from ubo_gui.menu import MenuWidget
from ubo_gui.notification import NotificationWidget
from ubo_gui.page import PAGE_MAX_ITEMS

from ubo_app.menu_app.notification_info import NotificationInfo
from ubo_app.store import autorun, dispatch, subscribe_event
from ubo_app.store.main import OpenApplicationEvent, SetMenuPathAction
from ubo_app.store.services.keypad import Key, KeypadKeyPressEvent
from ubo_app.store.services.notifications import (
    NotificationActionItem,
    NotificationDisplayType,
    NotificationsClearAction,
    NotificationsClearEvent,
    NotificationsDisplayEvent,
)
from ubo_app.store.services.voice import VoiceReadTextAction

from .home_page import HomePage

if TYPE_CHECKING:
    from kivy.uix.widget import Widget
    from ubo_gui.menu.types import Menu
    from ubo_gui.page import PageWidget


class MenuWidgetWithHomePage(MenuWidget):
    def render_items(self: MenuWidgetWithHomePage, *_: object) -> None:
        if self.depth <= 1:
            self.current_screen = HomePage(
                self.current_menu_items,
                name='Page 1 0',
                padding_bottom=self.padding_bottom,
                padding_top=self.padding_top,
            )
        else:
            super().render_items()


def set_path(menu_widget: MenuWidget, _: list[tuple[Menu, int] | PageWidget]) -> None:
    dispatch(
        SetMenuPathAction(
            path=[i.title for i in menu_widget.stack],
        ),
    )


class MenuAppCentral(UboApp):
    def __init__(self: MenuAppCentral, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.menu_widget = MenuWidgetWithHomePage()

        _self = weakref.ref(self)

        @autorun(lambda state: state.main.menu)
        @debounce(0.1, DebounceOptions(leading=True, trailing=True, time_window=0.1))
        async def _(menu: Menu | None) -> None:
            self = _self()
            if not self or not menu:
                return
            mainthread(self.menu_widget.set_root_menu)(menu)

        self.menu_widget.bind(page_index=self.handle_page_index_change)
        self.menu_widget.bind(current_menu=self.handle_page_index_change)

    def build(self: UboApp) -> Widget | None:
        root = super().build()
        self.menu_widget.padding_top = root.ids.header_layout.height
        self.menu_widget.padding_bottom = root.ids.footer_layout.height
        return root

    def handle_page_index_change(
        self: MenuAppCentral,
        *_: object,
    ) -> None:
        self.root.ids.header_layout.opacity = (
            1 if self.menu_widget.page_index == 0 else 0
        )
        self.root.ids.footer_layout.opacity = (
            1 if self.menu_widget.page_index >= self.menu_widget.pages - 1 else 0
        )

    def handle_title_change(self: MenuAppCentral, _: MenuWidget, title: str) -> None:
        self.root.title = title

    @functools.cached_property
    def central(self: MenuAppCentral) -> Widget | None:
        """Build the main menu and initiate it."""
        self.root.is_fullscreen = True
        self.root.title = self.menu_widget.title
        self.menu_widget.bind(title=self.handle_title_change)
        self.menu_widget.bind(current_screen=set_path)

        subscribe_event(
            KeypadKeyPressEvent,
            self.handle_key_press_event,
            keep_ref=False,
        )

        subscribe_event(
            NotificationsDisplayEvent,
            self.display_notification,
            keep_ref=False,
        )

        subscribe_event(
            OpenApplicationEvent,
            self.open_application,
            keep_ref=False,
        )

        return self.menu_widget

    @mainthread
    def handle_key_press_event(
        self: MenuAppCentral,
        key_press_event: KeypadKeyPressEvent,
    ) -> None:
        if key_press_event.key == Key.L1:
            self.menu_widget.select(0)
        if key_press_event.key == Key.L2:
            self.menu_widget.select(1)
        if key_press_event.key == Key.L3:
            self.menu_widget.select(2)
        if key_press_event.key == Key.BACK:
            self.menu_widget.go_back()
        if key_press_event.key == Key.UP:
            self.menu_widget.go_up()
        if key_press_event.key == Key.DOWN:
            self.menu_widget.go_down()

    @mainthread
    def display_notification(
        self: MenuAppCentral,
        event: NotificationsDisplayEvent,
    ) -> None:
        notification = event.notification

        @mainthread
        def dismiss() -> None:
            notification_application.dispatch('on_close')
            dispatch(
                NotificationsClearAction(notification=notification),
            )

        @mainthread
        def run_notification_action(
            action: NotificationActionItem,
        ) -> None:
            if action.dismiss_notification:
                dismiss()
            self.menu_widget.select_action_item(action)

        items = [
            replace(
                action,
                is_short=True,
                action=functools.partial(run_notification_action, action),
            )
            for action in notification.actions
        ]

        if notification.extra_information:

            def open_info() -> None:
                processed_visual_text = re.sub(
                    r'\{[^{}|]*\|[^{}|]*\}',
                    lambda x: x.group()[1:].split('|')[0],
                    notification.extra_information or '',
                )
                info_application = NotificationInfo(text=processed_visual_text)

                processed_audible_text = re.sub(
                    r'[^\x00-\xff]|\n',
                    '',
                    notification.extra_information or '',
                )
                dispatch(
                    VoiceReadTextAction(text=processed_audible_text),
                )
                self.menu_widget.open_application(info_application)

            items.append(
                NotificationActionItem(
                    icon='󰋼',
                    action=open_info,
                    label='',
                    is_short=True,
                    background_color=INFO_COLOR,
                ),
            )

        if notification.dismissable:
            items.append(
                NotificationActionItem(
                    icon='󰆴',
                    action=dismiss,
                    label='',
                    is_short=True,
                    background_color=DANGER_COLOR,
                ),
            )

        items = [None] * (PAGE_MAX_ITEMS - len(items)) + items

        notification_application = NotificationWidget(
            notification_title=notification.title,
            content=notification.content,
            icon=notification.icon,
            color=notification.color,
            items=items,
            title=f'Notification ({event.index+1}/{event.count})'
            if event.index is not None
            else ' ',
        )

        self.menu_widget.open_application(notification_application)

        if notification.display_type is NotificationDisplayType.FLASH:
            Clock.schedule_once(
                lambda _: notification_application.dispatch('on_close'),
                notification.flash_time,
            )

        @mainthread
        def clear_notification(event: NotificationsClearEvent) -> None:
            if event.notification == notification:
                notification_application.dispatch('on_close')
                unsubscribe()

        unsubscribe = subscribe_event(
            NotificationsClearEvent,
            clear_notification,
        )

    @mainthread
    def open_application(
        self: MenuAppCentral,
        event: OpenApplicationEvent,
    ) -> None:
        self.menu_widget.open_application(event.application)
