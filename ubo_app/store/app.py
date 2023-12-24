# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from typing import TYPE_CHECKING

from redux import BaseAction, Immutable

if TYPE_CHECKING:
    from ubo_gui.menu import Item


class RegisterAppActionPayload(Immutable):
    menu_item: Item


class RegisterAppAction(BaseAction):
    payload: RegisterAppActionPayload


class RegisterRegularAppAction(RegisterAppAction):
    ...


class RegisterSettingAppAction(RegisterAppAction):
    ...
