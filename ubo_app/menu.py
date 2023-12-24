# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from ubo_gui.app import UboApp

from .menu_central import MenuAppCentral
from .menu_footer import MenuAppFooter


class MenuApp(MenuAppCentral, MenuAppFooter, UboApp):
    """Menu application."""
