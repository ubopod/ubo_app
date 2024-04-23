# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import pathlib
import re
import weakref
from functools import cached_property
from typing import TYPE_CHECKING

from debouncer import DebounceOptions, debounce
from kivy.clock import Clock, mainthread
from kivy.lang.builder import Builder
from ubo_gui.app import UboApp
from ubo_gui.menu import MenuWidget
from ubo_gui.notification import NotificationWidget

from ubo_app.menu_app.notification_info import NotificationInfo
from ubo_app.store import autorun, dispatch, subscribe_event
from ubo_app.store.main import SetMenuPathAction
from ubo_app.store.services.keypad import Key, KeypadKeyPressEvent
from ubo_app.store.services.notifications import (
    NotificationDisplayType,
    NotificationsClearAction,
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
        if self.depth == 1:
            self.current_screen = HomePage(self.current_menu_items, name='Page 1 0')
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

    def handle_title_change(self: MenuAppCentral, _: MenuWidget, title: str) -> None:
        self.root.title = title

    @cached_property
    def central(self: MenuAppCentral) -> Widget | None:
        """Build the main menu and initiate it."""
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
        application = NotificationWidget(
            title='Notification',
            notification_title=notification.title,
            content=notification.content,
            icon=notification.icon,
            color=notification.color,
            has_extra_information=notification.extra_information is not None,
        )
        info_application = NotificationInfo(
            text=re.sub(
                r'\{[^{}|]*\|[^{}|]*\}',
                lambda x: x.group()[1:].split('|')[0],
                notification.extra_information or '',
            ),
        )

        application.bind(
            on_dismiss=lambda _: (
                application.dispatch('on_close'),
                dispatch(
                    NotificationsClearAction(notification=notification),
                ),
            ),
        )

        application.bind(
            on_info=lambda _: (
                dispatch(
                    VoiceReadTextAction(text=notification.extra_information or ''),
                ),
                self.menu_widget.open_application(info_application),
            ),
        )

        self.menu_widget.open_application(application)

        if notification.display_type is NotificationDisplayType.FLASH:
            Clock.schedule_once(
                lambda _: application.dispatch('on_dismiss'),
                notification.flash_time,
            )


Builder.load_file(
    pathlib.Path(__file__).parent.joinpath('home_page.kv').resolve().as_posix(),
)
