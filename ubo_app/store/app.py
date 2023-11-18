# ruff: noqa: D100, D101, D102, D103, D104, D107
import abc
from dataclasses import dataclass
from typing import Literal

from redux import BaseAction
from ubo_gui.menu import Item


@dataclass(frozen=True)
class RegisterAppActionPayload(BaseAction):
    menu_item: Item


RegisterAppActionType = Literal[
    'MAIN_REGISTER_REGULAR_APP',
    'MAIN_REGISTER_SETTING_APP',
]


@dataclass(frozen=True)
class RegisterAppAction(BaseAction):
    payload: RegisterAppActionPayload
    type: RegisterAppActionType


@dataclass(frozen=True)
class RegisterRegularAppAction(RegisterAppAction):
    type: Literal['MAIN_REGISTER_REGULAR_APP'] = 'MAIN_REGISTER_REGULAR_APP'


@dataclass(frozen=True)
class RegisterSettingAppAction(RegisterAppAction):
    type: Literal['MAIN_REGISTER_SETTING_APP'] = 'MAIN_REGISTER_SETTING_APP'
