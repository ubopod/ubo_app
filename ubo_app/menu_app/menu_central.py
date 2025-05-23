# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import weakref
from functools import cached_property
from typing import TYPE_CHECKING

from debouncer import DebounceOptions, debounce
from ubo_gui.app import UboApp
from ubo_gui.menu.menu_widget import MenuPageWidget, MenuWidget
from ubo_gui.menu.stack_item import StackApplicationItem, StackItem, StackMenuItem
from ubo_gui.page import PageWidget
from ubo_gui.utils import mainthread_if_needed

from ubo_app.constants import DEBUG_MENU
from ubo_app.logger import logger
from ubo_app.menu_app.home_page import HomePage
from ubo_app.menu_app.menu_notification_handler import MenuNotificationHandler
from ubo_app.store.core.types import (
    CloseApplicationEvent,
    MenuChooseByIconEvent,
    MenuChooseByIndexEvent,
    MenuChooseByLabelEvent,
    MenuGoBackEvent,
    MenuGoHomeEvent,
    MenuScrollDirection,
    MenuScrollEvent,
    OpenApplicationEvent,
    SetAreEnclosuresVisibleAction,
    SetMenuPathAction,
)
from ubo_app.store.main import store
from ubo_app.store.services.notifications import NotificationsDisplayEvent
from ubo_app.store.ubo_actions import get_registered_application
from ubo_app.utils.gui import UboPageWidget

if TYPE_CHECKING:
    from collections.abc import Sequence

    from kivy.uix.widget import Widget
    from ubo_gui.menu.types import Item, Menu


class MenuWidgetWithHomePage(MenuWidget):
    @cached_property
    def home_page(self: MenuWidgetWithHomePage) -> HomePage:
        return HomePage(
            name='Page 1 0',
            padding_bottom=self.padding_bottom,
            padding_top=self.padding_top,
        )

    def _render_menu(self: MenuWidgetWithHomePage, menu: Menu) -> MenuPageWidget:
        if self.depth <= 1:
            self.home_page.items = self.current_menu_items
            self.current_screen = self.home_page
            return self.home_page
        return super()._render_menu(menu)


class MenuAppCentral(MenuNotificationHandler, UboApp):
    def __init__(self: MenuAppCentral, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.menu_widget = MenuWidgetWithHomePage(render_surroundings=True)

        self.menu_widget.bind(page_index=self.handle_page_index_change)
        self.menu_widget.bind(current_menu=self.handle_page_index_change)
        self.menu_widget.bind(title=self.handle_title_change)
        self.menu_widget.bind(stack=self.handle_stack_change)

        if DEBUG_MENU:
            menu_representation = 'Menu:\n' + repr(self.menu_widget)
            self.menu_widget.bind(stack=lambda *_: logger.info(menu_representation))

        _self = weakref.ref(self)

        @store.autorun(lambda state: state.main.menu)
        @debounce(0.1, DebounceOptions(leading=True, trailing=True, time_window=0.1))
        def _(menu: Menu | None) -> None:
            self = _self()
            if not self or not menu:
                return
            self.menu_widget.set_root_menu(menu)

    def build(self) -> Widget | None:
        root = super().build()
        if root:
            self.menu_widget.padding_top = root.ids.header_layout.height
            self.menu_widget.padding_bottom = root.ids.footer_layout.height

        return root

    def handle_page_index_change(
        self: MenuAppCentral,
        *_: object,
    ) -> None:
        store.dispatch(
            SetAreEnclosuresVisibleAction(
                is_header_visible=self.menu_widget.page_index == 0,
                is_footer_visible=self.menu_widget.page_index
                >= self.menu_widget.pages - 1,
            ),
        )

    def handle_title_change(self: MenuAppCentral, _: MenuWidget, title: str) -> None:
        self.root.title = title

    def handle_stack_change(
        self: MenuAppCentral,
        _: MenuWidget,
        stack: list[StackItem],
    ) -> None:
        store.dispatch(
            SetMenuPathAction(
                path=[
                    stack_item.selection.key
                    for stack_item in stack
                    if isinstance(stack_item, StackMenuItem) and stack_item.selection
                ],
                depth=len(stack),
            ),
        )

    @cached_property
    def central(self: MenuAppCentral) -> Widget | None:
        """Build the main menu and initiate it."""
        self.root.title = self.menu_widget.title

        store.subscribe_event(
            NotificationsDisplayEvent,
            self.display_notification,
            keep_ref=False,
        )

        store.subscribe_event(
            OpenApplicationEvent,
            self.open_application,
            keep_ref=False,
        )
        store.subscribe_event(
            CloseApplicationEvent,
            self.close_application,
            keep_ref=False,
        )
        store.subscribe_event(
            MenuGoHomeEvent,
            self.go_home,
            keep_ref=False,
        )
        store.subscribe_event(
            MenuGoBackEvent,
            self.go_back,
            keep_ref=False,
        )
        store.subscribe_event(
            MenuChooseByIconEvent,
            self.select_by_icon,
            keep_ref=False,
        )
        store.subscribe_event(
            MenuChooseByLabelEvent,
            self.select_by_label,
            keep_ref=False,
        )
        store.subscribe_event(
            MenuChooseByIndexEvent,
            self.select_by_index,
            keep_ref=False,
        )
        store.subscribe_event(
            MenuScrollEvent,
            self.scroll,
            keep_ref=False,
        )

        return self.menu_widget

    @mainthread_if_needed
    def open_application(self: MenuAppCentral, event: OpenApplicationEvent) -> None:
        application = get_registered_application(event.application_id)
        self.menu_widget.open_application(
            application(*event.initialization_args, **event.initialization_kwargs),
        )

    def close_application(self: MenuAppCentral, event: CloseApplicationEvent) -> None:
        for item in self.menu_widget.stack:
            if (
                isinstance(item, StackApplicationItem)
                and hasattr(item.application, 'id')
                and isinstance(item.application, UboPageWidget)
                and item.application.id == event.application_instance_id
            ):
                self.menu_widget.close_application(item.application)

    def go_home(self: MenuAppCentral, _: MenuGoHomeEvent) -> None:
        self.menu_widget.go_home()

    def go_back(self: MenuAppCentral, _: MenuGoBackEvent) -> None:
        self.menu_widget.go_back()

    def select_by_icon(self: MenuAppCentral, event: MenuChooseByIconEvent) -> None:
        current_page = self.menu_widget.current_screen
        if current_page is None:
            msg = 'No current page'
            raise ValueError(msg)
        if not isinstance(current_page, PageWidget):
            msg = 'Current page is not a StackMenuItem'
            raise TypeError(msg)
        if current_page.items is None:
            msg = 'No items in current page'
            raise TypeError(msg)
        items: Sequence[Item | None] = current_page.items
        filtered_items = [item for item in items if item and item.icon == event.icon]
        if not filtered_items:
            msg = f'No item with icon "{event.icon}"'
            raise ValueError(msg)
        if len(filtered_items) > 1:
            msg = (
                f'Expected 1 item with icon "{event.icon}", found '
                f'"{len(filtered_items)}"'
            )
            raise ValueError(msg)
        self.menu_widget.select_item(filtered_items[0], parent=self.menu_widget.top)

    def select_by_label(
        self: MenuAppCentral,
        event: MenuChooseByLabelEvent,
    ) -> None:
        from ubo_gui.page import PageWidget

        current_page = self.menu_widget.current_screen
        if current_page is None:
            msg = 'No current page'
            raise ValueError(msg)
        if not isinstance(current_page, PageWidget):
            msg = 'Current page is not a StackMenuItem'
            raise TypeError(msg)
        if current_page.items is None:
            msg = 'No items in current page'
            raise TypeError(msg)
        items: Sequence[Item | None] = current_page.items
        filtered_items = [item for item in items if item and item.label == event.label]
        if not filtered_items:
            msg = f'No item with label "{event.label}"'
            raise ValueError(msg)
        if len(filtered_items) > 1:
            msg = (
                f'Expected 1 item with label "{event.label}", found '
                f'"{len(filtered_items)}"'
            )
            raise ValueError(msg)
        self.menu_widget.select_item(filtered_items[0], parent=self.menu_widget.top)

    def select_by_index(
        self: MenuAppCentral,
        event: MenuChooseByIndexEvent,
    ) -> None:
        self.menu_widget.select(event.index)

    def scroll(self: MenuAppCentral, event: MenuScrollEvent) -> None:
        if event.direction == MenuScrollDirection.UP:
            self.menu_widget.go_up()
        elif event.direction == MenuScrollDirection.DOWN:
            self.menu_widget.go_down()
