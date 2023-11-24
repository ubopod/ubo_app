# ruff: noqa: D100, D101, D102, D103, D104, D107
from typing import Literal, TypeGuard

from redux import BaseAction, Immutable
from ubo_gui.menu import Item


class RegisterAppActionPayload(Immutable):
    menu_item: Item


RegisterAppActionType = Literal[
    'MAIN_REGISTER_REGULAR_APP',
    'MAIN_REGISTER_SETTING_APP',
]


class RegisterAppAction(BaseAction):
    payload: RegisterAppActionPayload
    type: RegisterAppActionType


class RegisterRegularAppAction(RegisterAppAction):
    type: Literal['MAIN_REGISTER_REGULAR_APP'] = 'MAIN_REGISTER_REGULAR_APP'


class RegisterSettingAppAction(RegisterAppAction):
    type: Literal['MAIN_REGISTER_SETTING_APP'] = 'MAIN_REGISTER_SETTING_APP'


def is_app_registration_action(action: BaseAction) -> TypeGuard[RegisterAppAction]:
    return action.type in ('MAIN_REGISTER_REGULAR_APP', 'MAIN_REGISTER_SETTING_APP')
