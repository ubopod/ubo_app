"""Ubo menu application."""

from __future__ import annotations

from typing_extensions import override
from ubo_gui.app import UboApp

from ubo_app.menu_app.menu_central import MenuAppCentral
from ubo_app.menu_app.menu_footer import MenuAppFooter
from ubo_app.menu_app.menu_header import MenuAppHeader


class MenuApp(MenuAppCentral, MenuAppFooter, MenuAppHeader, UboApp):
    """Menu application."""

    @override
    def on_start(self: MenuApp) -> None:
        """Start the application."""
        from ubo_app.side_effects import setup_side_effects

        setup_side_effects()
