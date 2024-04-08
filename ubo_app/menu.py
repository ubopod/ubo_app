"""Ubo menu application."""

from __future__ import annotations

from ubo_gui.app import UboApp

from .menu_central import MenuAppCentral
from .menu_footer import MenuAppFooter


class MenuApp(MenuAppCentral, MenuAppFooter, UboApp):
    """Menu application."""

    def on_start(self: MenuApp) -> None:
        """Start the application."""
        from ubo_app.side_effects import setup_side_effects

        setup_side_effects()
