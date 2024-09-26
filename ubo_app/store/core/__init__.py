# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from dataclasses import field
from enum import StrEnum
from typing import TYPE_CHECKING

from immutable import Immutable
from redux import BaseAction, BaseEvent


class SettingsCategory(StrEnum):
    NETWORK = 'Network'
    REMOTE = 'Remote'
    OS = 'OS'
    SPEECH = 'Speech'
    DOCKER = 'Docker'


SETTINGS_ICONS = {
    SettingsCategory.NETWORK: '󰛳',
    SettingsCategory.REMOTE: '󰑔',
    SettingsCategory.OS: '󰕈',
    SettingsCategory.SPEECH: '󰔊',
    SettingsCategory.DOCKER: '󰡨',
}


if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_gui.menu.types import Item, Menu
    from ubo_gui.page import PageWidget


class MainAction(BaseAction): ...


class UpdateLightDMState(MainAction):
    is_active: bool
    is_enable: bool


def service_default_factory() -> str:
    from ubo_app.service import service_id

    return service_id


class RegisterAppAction(MainAction):
    menu_item: Item
    service: str = field(default_factory=service_default_factory)
    key: str | None = None


class RegisterRegularAppAction(RegisterAppAction): ...


class RegisterSettingAppAction(RegisterAppAction):
    category: SettingsCategory
    priority: int | None = None


class PowerAction(MainAction): ...


class PowerOffAction(PowerAction): ...


class RebootAction(PowerAction): ...


class SetMenuPathAction(MainAction):
    path: Sequence[str]
    depth: int


class MainEvent(BaseEvent): ...


class InitEvent(MainEvent): ...


class ChooseMenuItemByIconEvent(MainEvent):
    icon: str


class ChooseMenuItemByLabelEvent(MainEvent):
    label: str


class ChooseMenuItemByIndexEvent(MainEvent):
    index: int


ChooseMenuItemEvent = (
    ChooseMenuItemByIconEvent | ChooseMenuItemByLabelEvent | ChooseMenuItemByIndexEvent
)


class OpenApplicationEvent(MainEvent):
    application: PageWidget


class CloseApplicationEvent(MainEvent):
    application: PageWidget


class PowerEvent(MainEvent): ...


class PowerOffEvent(PowerEvent): ...


class RebootEvent(PowerEvent): ...


class MainState(Immutable):
    menu: Menu | None = None
    path: Sequence[str] = field(default_factory=list)
    depth: int = 0
    settings_items_priorities: dict[str, int] = field(default_factory=dict)
