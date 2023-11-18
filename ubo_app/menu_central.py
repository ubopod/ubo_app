# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import uuid
from functools import cached_property
from threading import Thread
from typing import TYPE_CHECKING

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from ubo_gui.app import UboApp
from ubo_gui.gauge import GaugeWidget
from ubo_gui.menu import MenuWidget
from ubo_gui.menu.constants import SHORT_WIDTH
from ubo_gui.volume import VolumeWidget

from ubo_app.store.main_selectors import current_menu

from .store import autorun

if TYPE_CHECKING:
    from kivy.uix.widget import Widget
    from ubo_gui.menu import Menu
    from ubo_gui.page import PageWidget


class MenuAppCentral(UboApp):
    @cached_property
    def menu_widget(self: MenuAppCentral) -> MenuWidget:
        """Build the main menu and initiate it."""
        menu_widget = MenuWidget()

        @autorun(lambda _: current_menu())
        def sync_menu(selector_result: Menu) -> None:
            menu_widget.set_current_menu(selector_result)

        @autorun(lambda state: state.main.page)
        def sync_page(selector_result: int) -> None:
            menu_widget.page_index = selector_result
            menu_widget.update()

        @autorun(lambda state: state.main.current_application)
        def sync_application(selector_result: PageWidget) -> None:
            application_instance = selector_result(name=uuid.uuid4().hex)
            menu_widget.open_application(application_instance)

        def title_callback(_: MenuWidget, title: str) -> None:
            self.root.title = title

        self.root.title = menu_widget.title
        menu_widget.bind(title=title_callback)

        return menu_widget

    @cached_property
    def cpu_gauge(self: MenuAppCentral) -> GaugeWidget:
        import psutil

        gauge = GaugeWidget(value=0, fill_color='#24D636', label='CPU')

        value = 0

        def set_value(_: float) -> None:
            gauge.value = value

        def calculate_value() -> None:
            nonlocal value
            value = psutil.cpu_percent(interval=1, percpu=False)
            Clock.schedule_once(set_value)

        Clock.schedule_interval(
            lambda _: Thread(target=calculate_value).start(),
            1,
        )

        return gauge

    @cached_property
    def ram_gauge(self: MenuAppCentral) -> GaugeWidget:
        import psutil

        gauge = GaugeWidget(
            value=psutil.virtual_memory().percent,
            fill_color='#D68F24',
            label='RAM',
        )

        def set_value(_: int) -> None:
            gauge.value = psutil.virtual_memory().percent

        Clock.schedule_interval(set_value, 1)

        return gauge

    @cached_property
    def central(self: MenuAppCentral) -> Widget:
        horizontal_layout = BoxLayout()

        self.menu_widget.size_hint = (None, 1)
        self.menu_widget.width = dp(SHORT_WIDTH)
        horizontal_layout.add_widget(self.menu_widget)

        central_column = BoxLayout(
            orientation='vertical',
            spacing=dp(12),
            padding=dp(16),
        )
        central_column.add_widget(self.cpu_gauge)
        central_column.add_widget(self.ram_gauge)
        central_column.size_hint = (1, 1)
        horizontal_layout.add_widget(central_column)

        right_column = BoxLayout(orientation='vertical')
        right_column.add_widget(VolumeWidget(value=40))
        right_column.size_hint = (None, 1)
        right_column.width = dp(SHORT_WIDTH)
        horizontal_layout.add_widget(right_column)

        @autorun(lambda state: len(state.main.path) != 0)
        def handle_depth_change(selector_result: bool) -> None:  # noqa: FBT001
            is_deep = selector_result
            if is_deep:
                self.menu_widget.size_hint = (1, 1)
                central_column.size_hint = (0, 1)
                right_column.size_hint = (0, 1)
            else:
                self.menu_widget.size_hint = (None, 1)
                self.menu_widget.width = dp(SHORT_WIDTH)
                central_column.size_hint = (1, 1)
                right_column.size_hint = (None, 1)

        return horizontal_layout
