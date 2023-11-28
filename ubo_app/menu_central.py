# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

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
from ubo_gui.page import PageWidget
from ubo_gui.volume import VolumeWidget

from ubo_app.store.keypad import Key, KeypadKeyPressEvent
from ubo_app.store.main import SetMenuPathAction, SetMenuPathActionPayload

from .store import autorun, dispatch, subscribe_event

if TYPE_CHECKING:
    from kivy.uix.widget import Widget
    from ubo_gui.menu.types import Menu


class MenuAppCentral(UboApp):
    @cached_property
    def menu_widget(self: MenuAppCentral) -> MenuWidget:
        """Build the main menu and initiate it."""
        menu_widget = MenuWidget()

        @autorun(lambda state: state.main.current_menu)
        def sync_current_menu(selector_result: Menu | None) -> None:
            menu_widget.set_root_menu(selector_result)

        def handle_title_change(_: MenuWidget, title: str) -> None:
            self.root.title = title

        self.root.title = menu_widget.title
        menu_widget.bind(title=handle_title_change)
        menu_widget.bind(
            stack=lambda _, path: dispatch(
                SetMenuPathAction(
                    payload=SetMenuPathActionPayload(
                        path=[
                            i.name if isinstance(i, PageWidget) else i[0]['title']
                            for i in path
                        ],
                    ),
                ),
            ),
        )

        def handle_key_press_event(key_press_event: KeypadKeyPressEvent) -> None:
            if key_press_event.payload.key == Key.L1:
                menu_widget.select(0)
            if key_press_event.payload.key == Key.L2:
                menu_widget.select(1)
            if key_press_event.payload.key == Key.L3:
                menu_widget.select(2)
            if key_press_event.payload.key == Key.BACK:
                menu_widget.go_back()
            if key_press_event.payload.key == Key.UP:
                menu_widget.go_up()
            if key_press_event.payload.key == Key.DOWN:
                menu_widget.go_down()

        subscribe_event(KeypadKeyPressEvent, handle_key_press_event)

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
        volume_widget = VolumeWidget()
        right_column.add_widget(volume_widget)
        right_column.size_hint = (None, 1)
        right_column.width = dp(SHORT_WIDTH)
        horizontal_layout.add_widget(right_column)

        @autorun(
            lambda state: getattr(getattr(state, 'sound', None), 'output_volume', 0),
        )
        def sync_output_volume(selector_result: float) -> None:
            volume_widget.value = selector_result * 100
            self.root.reset_fps_control_queue()

        def handle_depth_change(_: MenuWidget, depth: int) -> None:
            is_deep = depth > 0
            if is_deep:
                self.menu_widget.size_hint = (1, 1)
                central_column.size_hint = (0, 1)
                right_column.size_hint = (0, 1)
            else:
                self.menu_widget.size_hint = (None, 1)
                self.menu_widget.width = dp(SHORT_WIDTH)
                central_column.size_hint = (1, 1)
                right_column.size_hint = (None, 1)

        self.menu_widget.bind(depth=handle_depth_change)

        return horizontal_layout
