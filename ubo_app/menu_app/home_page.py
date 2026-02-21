# ruff: noqa: D100, D101, D102, D107
from __future__ import annotations

import pathlib
from functools import cached_property
from typing import TYPE_CHECKING

from kivy.clock import Clock
from kivy.lang.builder import Builder
from ubo_gui.gauge import GaugeWidget
from ubo_gui.menu.constants import PAGE_SIZE
from ubo_gui.menu.menu_widget import MenuPageWidget
from ubo_gui.volume import VolumeWidget

from ubo_app.store.main import store

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

        from ubo_app.utils.persistent_store import read_from_persistent_store

        initial_volume = read_from_persistent_store(
            'audio_state:playback_volume',
            default=0.5,
        )
        self.volume_widget = VolumeWidget(value=initial_volume * 100)
        self.ids.right_column.add_widget(self.volume_widget)

        def set_volume(_: float) -> None:
            try:
                vol = store._state.audio.playback_volume  # noqa: SLF001
                self.volume_widget.value = vol * 100
            except AttributeError:
                pass

        Clock.schedule_interval(set_volume, 1)

    @cached_property
    def cpu_gauge(self: HomePage) -> GaugeWidget:
        import psutil

        gauge = GaugeWidget(
            value=psutil.cpu_percent(percpu=False),
            fill_color='#24D636',
            label='CPU',
        )

        def set_value(_: float) -> None:
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

        def set_value(_: float) -> None:
            gauge.value = psutil.virtual_memory().percent

        Clock.schedule_interval(set_value, 1)

        return gauge


Builder.load_file(
    pathlib.Path(__file__).parent.joinpath('home_page.kv').resolve().as_posix(),
)
