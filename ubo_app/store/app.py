# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from typing import TYPE_CHECKING

from redux import BaseAction

if TYPE_CHECKING:
    from ubo_gui.menu import Item


class RegisterAppAction(BaseAction):
    menu_item: Item


class RegisterRegularAppAction(RegisterAppAction):
    ...


class RegisterSettingAppAction(RegisterAppAction):
    ...
