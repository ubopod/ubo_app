# ruff: noqa: D100, D101, D102, D107
from __future__ import annotations

import pathlib
from functools import cached_property
from typing import TYPE_CHECKING

from kivy.lang.builder import Builder
from ubo_gui.gauge import GaugeWidget
from ubo_gui.menu.constants import PAGE_SIZE
from ubo_gui.menu.menu_widget import MenuPageWidget
from ubo_gui.volume import VolumeWidget

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_gui.menu.types import Item


class HomePage(MenuPageWidget):
    def __init__(
        self: HomePage,
        items: Sequence[Item | None] = [],
        *args: object,
        **kwargs: object,
    ) -> None:
        super().__init__(
            [None, *items, None],
            *args,
            **kwargs,
            count=PAGE_SIZE,
            render_surroundings=False,
        )

        self.ids.central_column.add_widget(self.cpu_gauge)
        self.ids.central_column.add_widget(self.ram_gauge)

        # Initial volume at 50% - will be updated by ViewRenderer via gRPC
        self.volume_widget = VolumeWidget(value=50)
        self.ids.right_column.add_widget(self.volume_widget)

    @cached_property
    def cpu_gauge(self: HomePage) -> GaugeWidget:
        return GaugeWidget(
            value=0,
            fill_color='#24D636',
            label='CPU',
        )

    @cached_property
    def ram_gauge(self: HomePage) -> GaugeWidget:
        return GaugeWidget(
            value=0,
            fill_color='#D68F24',
            label='RAM',
        )


Builder.load_file(
    pathlib.Path(__file__).parent.joinpath('home_page.kv').resolve().as_posix(),
)
