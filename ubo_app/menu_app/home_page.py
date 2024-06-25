# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import pathlib
from functools import cached_property
from typing import TYPE_CHECKING

from kivy.clock import Clock
from kivy.lang.builder import Builder
from ubo_gui.gauge import GaugeWidget
from ubo_gui.menu.constants import PAGE_SIZE
from ubo_gui.page import PageWidget
from ubo_gui.volume import VolumeWidget

from ubo_app.store.main import autorun

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_gui.menu.types import Item


class HomePage(PageWidget):
    def __init__(
        self: HomePage,
        items: Sequence[Item | None] = [],
        *args: object,
        **kwargs: object,
    ) -> None:
        super().__init__(
            [None, *items, None],
            *args,
            count=PAGE_SIZE + 2,
            offset=1,
            render_surroundings=True,
            **kwargs,
        )

        self.ids.central_column.add_widget(self.cpu_gauge)
        self.ids.central_column.add_widget(self.ram_gauge)

        self.volume_widget = VolumeWidget()
        self.ids.right_column.add_widget(self.volume_widget)

        autorun(lambda state: state.sound.playback_volume)(self._sync_output_volume)

    def set_items(self: HomePage, items: Sequence[Item | None] = []) -> None:
        self.items = [None, *items, None]

    def _sync_output_volume(self: HomePage, selector_result: float) -> None:
        self.volume_widget.value = selector_result * 100

    @cached_property
    def cpu_gauge(self: HomePage) -> GaugeWidget:
        import psutil

        gauge = GaugeWidget(
            value=psutil.cpu_percent(percpu=False),
            fill_color='#24D636',
            label='CPU',
        )

        def set_value(_: int) -> None:
            gauge.value = psutil.cpu_percent(percpu=False)

        Clock.schedule_interval(set_value, 1)

        return gauge

    @cached_property
    def ram_gauge(self: HomePage) -> GaugeWidget:
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


Builder.load_file(
    pathlib.Path(__file__).parent.joinpath('home_page.kv').resolve().as_posix(),
)
