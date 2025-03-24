"""Ubo menu application."""

from __future__ import annotations

from typing import TYPE_CHECKING

from typing_extensions import override
from ubo_gui.app import UboApp

from ubo_app.menu_app.menu_central import MenuAppCentral
from ubo_app.menu_app.menu_footer import MenuAppFooter
from ubo_app.menu_app.menu_header import MenuAppHeader
from ubo_app.store.main import store
from ubo_app.store.services.display import DisplayRerenderEvent
from ubo_app.store.settings.types import SettingsSetDebugModeEvent

if TYPE_CHECKING:
    from ubo_app.utils.types import Subscriptions


class MenuApp(MenuAppCentral, MenuAppFooter, MenuAppHeader, UboApp):
    """Menu application."""

    def __init__(self: MenuApp, **kwargs: object) -> None:
        """Initialize the application."""
        super().__init__(**kwargs)
        self.subscriptions: Subscriptions = []
        self.is_stopped = False

    def set_debug_mode(self: MenuApp, event: SettingsSetDebugModeEvent) -> None:
        """Set the debug mode."""
        self.root.show_update_regions = event.is_enabled

    def rerender(self: MenuApp) -> None:
        """Re-render the application."""
        self.root.previous_frame = None

    @override
    def on_start(self: MenuApp) -> None:
        """Start the application."""
        from ubo_app.side_effects import setup_side_effects

        self.subscriptions = setup_side_effects()

        store.subscribe_event(
            SettingsSetDebugModeEvent,
            self.set_debug_mode,
            keep_ref=False,
        )
        store.subscribe_event(DisplayRerenderEvent, self.rerender, keep_ref=False)

    @override
    def stop(self, *largs: object) -> object:
        """Stop the application."""
        return_value = super().stop(*largs)
        self.is_stopped = True
        for cleanup in self.subscriptions:
            cleanup()
        return return_value
