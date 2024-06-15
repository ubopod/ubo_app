# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from dataclasses import field
from enum import StrEnum
from typing import TYPE_CHECKING

from immutable import Immutable
from redux import BaseAction, BaseEvent


class SettingsCategory(StrEnum):
    NETWORK = 'Network'
    ACCESSIBILITY = 'Accessibility'
    UTILITIES = 'Utilities'
    REMOTE = 'Remote'
    APPS = 'Apps'


SETTINGS_ICONS = {
    SettingsCategory.NETWORK: '󰛳',
    SettingsCategory.ACCESSIBILITY: '󰖤',
    SettingsCategory.UTILITIES: '󰟻',
    SettingsCategory.REMOTE: '󰑔',
    SettingsCategory.APPS: '󰀻',
}


if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_gui.menu.types import Item, Menu
    from ubo_gui.page import PageWidget


class MainAction(BaseAction): ...


class RegisterAppAction(MainAction):
    menu_item: Item


class UpdateLightDMState(MainAction):
    is_active: bool
    is_enable: bool


class RegisterRegularAppAction(RegisterAppAction): ...


class RegisterSettingAppAction(RegisterAppAction):
    category: SettingsCategory
    priority: int | None = None


class PowerOffAction(MainAction): ...


class SetMenuPathAction(MainAction):
    path: Sequence[str]


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


class PowerOffEvent(MainEvent): ...


class MainState(Immutable):
    menu: Menu | None = None
    path: Sequence[str] = field(default_factory=list)
    settings_items_priorities: dict[str, int] = field(default_factory=dict)
