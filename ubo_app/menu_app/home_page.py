# ruff: noqa: D100, D101, D102, D107
from __future__ import annotations

import pathlib
from functools import cached_property
from typing import TYPE_CHECKING

from kivy.clock import mainthread
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
        items: Sequence[Item | None] = (),
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

        self._setup_autoruns()

    def _setup_autoruns(self: HomePage) -> None:
        """Set up autoruns that sync gauges and volume with store state."""
        from redux import AutorunOptions

        store.autorun(
            lambda state: state.audio.playback_volume
            if hasattr(state, 'audio')
            else 0.0,
            options=AutorunOptions(keep_ref=False),
        )(self._on_volume_changed)

        store.autorun(
            lambda state: state.system.cpu_percent
            if hasattr(state, 'system')
            else 0.0,
            options=AutorunOptions(keep_ref=False),
        )(self._on_cpu_changed)

        store.autorun(
            lambda state: state.system.ram_percent
            if hasattr(state, 'system')
            else 0.0,
            options=AutorunOptions(keep_ref=False),
        )(self._on_ram_changed)

    @mainthread
    def _on_volume_changed(self: HomePage, volume: float) -> None:
        self.volume_widget.value = volume * 100

    @mainthread
    def _on_cpu_changed(self: HomePage, cpu_percent: float) -> None:
        self.cpu_gauge.value = cpu_percent

    @mainthread
    def _on_ram_changed(self: HomePage, ram_percent: float) -> None:
        self.ram_gauge.value = ram_percent

    @cached_property
    def cpu_gauge(self: HomePage) -> GaugeWidget:
        return GaugeWidget(
            value=0.0,
            fill_color='#24D636',
            label='CPU',
        )

    @cached_property
    def ram_gauge(self: HomePage) -> GaugeWidget:
        return GaugeWidget(
            value=0.0,
            fill_color='#D68F24',
            label='RAM',
        )


Builder.load_file(
    pathlib.Path(__file__).parent.joinpath('home_page.kv').resolve().as_posix(),
)
