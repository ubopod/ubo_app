# ruff: noqa: D100, D101, D102, D103, D104, D107
from redux import BaseAction, Immutable
from ubo_gui.menu import Item


class RegisterAppActionPayload(Immutable):
    menu_item: Item


class RegisterAppAction(BaseAction):
    payload: RegisterAppActionPayload


class RegisterRegularAppAction(RegisterAppAction):
    ...


class RegisterSettingAppAction(RegisterAppAction):
    ...
