# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import os

from headless_kivy_pi import setup_headless

os.environ['KIVY_METRICS_DENSITY'] = '1'
os.environ['KIVY_NO_CONFIG'] = '1'
os.environ['KIVY_NO_FILELOG'] = '1'

setup_headless()

from ubo_gui.app import UboApp  # noqa: E402

from .menu_central import MenuAppCentral  # noqa: E402
from .menu_footer import MenuAppFooter  # noqa: E402


class MenuApp(MenuAppCentral, MenuAppFooter, UboApp):
    """Menu application."""
