"""Ubo menu application."""

from __future__ import annotations

from typing import TYPE_CHECKING

from redux import AutorunOptions
from typing_extensions import override
from ubo_gui.app import UboApp

from ubo_app.menu_app.menu_central import MenuAppCentral
from ubo_app.menu_app.menu_footer import MenuAppFooter
from ubo_app.menu_app.menu_header import MenuAppHeader
from ubo_app.store.main import store
from ubo_app.store.services.display import DisplayRerenderEvent

if TYPE_CHECKING:
    from ubo_app.utils.types import Subscriptions


class MenuApp(MenuAppCentral, MenuAppFooter, MenuAppHeader, UboApp):
    """Menu application."""

    def __init__(self: MenuApp, **kwargs: object) -> None:
        """Initialize the application."""
        super().__init__(**kwargs)
        self.subscriptions: Subscriptions = []
        self.is_stopped = False

    def set_visual_debug_mode(self: MenuApp, visual_debug: bool) -> None:  # noqa: FBT001
        """Set the visual debug mode."""
        self.root.show_update_regions = visual_debug

    def rerender(self: MenuApp) -> None:
        """Re-render the application."""
        self.root.previous_frame = None

    @override
    def on_start(self: MenuApp) -> None:
        """Start the application."""
        from ubo_app.side_effects import setup_side_effects

        self.subscriptions = setup_side_effects()

        store.autorun(
            lambda state: state.settings.visual_debug,
            options=AutorunOptions(keep_ref=False),
        )(self.set_visual_debug_mode)
        store.subscribe_event(DisplayRerenderEvent, self.rerender, keep_ref=False)

    @override
    def stop(self, *largs: object) -> None:
        """Stop the application."""
        super().stop(*largs)
        self.is_stopped = True
        for cleanup in self.subscriptions:
            cleanup()
