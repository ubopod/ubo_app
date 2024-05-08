# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import functools
import weakref
from typing import TYPE_CHECKING

from debouncer import DebounceOptions, debounce
from kivy.clock import mainthread
from ubo_gui.app import UboApp, cached_property
from ubo_gui.menu import MenuWidget

from ubo_app.menu_app.menu_notification_handler import MenuNotificationHandler
from ubo_app.store import autorun, dispatch, subscribe_event
from ubo_app.store.main import (
    CloseApplicationEvent,
    OpenApplicationEvent,
    SetMenuPathAction,
)
from ubo_app.store.services.keypad import Key, KeypadKeyPressEvent
from ubo_app.store.services.notifications import NotificationsDisplayEvent

from .home_page import HomePage

if TYPE_CHECKING:
    from kivy.uix.widget import Widget
    from ubo_gui.menu.types import Menu
    from ubo_gui.page import PageWidget


class MenuWidgetWithHomePage(MenuWidget):
    @cached_property
    def home_page(self: MenuWidgetWithHomePage) -> HomePage:
        return HomePage(
            name='Page 1 0',
            padding_bottom=self.padding_bottom,
            padding_top=self.padding_top,
        )

    def render_items(self: MenuWidgetWithHomePage, *_: object) -> None:
        if self.depth <= 1:
            self.home_page.set_items(self.current_menu_items)
            self.current_screen = self.home_page
        else:
            super().render_items()


def set_path(menu_widget: MenuWidget, _: list[tuple[Menu, int] | PageWidget]) -> None:
    dispatch(
        SetMenuPathAction(
            path=[i.title for i in menu_widget.stack],
        ),
    )


class MenuAppCentral(MenuNotificationHandler, UboApp):
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

        subscribe_event(OpenApplicationEvent, self.open_application, keep_ref=False)
        subscribe_event(CloseApplicationEvent, self.close_application, keep_ref=False)

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
    def open_application(self: MenuAppCentral, event: OpenApplicationEvent) -> None:
        self.menu_widget.open_application(event.application)

    @mainthread
    def close_application(self: MenuAppCentral, event: CloseApplicationEvent) -> None:
        self.menu_widget.close_application(event.application)
