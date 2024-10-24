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


class MenuScrollDirection(StrEnum):
    UP = 'up'
    DOWN = 'down'


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


class MenuAction(MainAction): ...


class MenuGoBackAction(MenuAction): ...


class MenuGoHomeAction(MenuAction): ...


class MenuChooseByIconAction(MenuAction):
    icon: str


class MenuChooseByLabelAction(MenuAction):
    label: str


class MenuChooseByIndexAction(MenuAction):
    index: int


class MenuScrollAction(MenuAction):
    direction: MenuScrollDirection


class OpenApplicationAction(MainAction):
    application: PageWidget


class CloseApplicationAction(MainAction):
    application: PageWidget


class MainEvent(BaseEvent): ...


class InitEvent(MainEvent): ...


class MenuEvent(MainEvent): ...


class MenuGoBackEvent(MenuEvent): ...


class MenuGoHomeEvent(MenuEvent): ...


class MenuChooseByIconEvent(MenuEvent):
    icon: str


class MenuChooseByLabelEvent(MenuEvent):
    label: str


class MenuChooseByIndexEvent(MenuEvent):
    index: int


class MenuScrollEvent(MenuEvent):
    direction: MenuScrollDirection


class OpenApplicationEvent(MainEvent):
    application: PageWidget


class CloseApplicationEvent(MainEvent):
    application: PageWidget


class PowerEvent(MainEvent): ...


class PowerOffEvent(PowerEvent): ...


class RebootEvent(PowerEvent): ...


class ScreenshotEvent(MainEvent):
    """Event for taking a screenshot."""


class SnapshotEvent(MainEvent):
    """Event for taking a snapshot of the store."""


class StoreRecordedSequenceEvent(MainEvent):
    """Event for storing a recorded sequence."""

    recorded_sequence: list[BaseAction]


class ReplayRecordedSequenceEvent(MainEvent):
    """Event for replaying a recorded sequence."""


class MainState(Immutable):
    menu: Menu | None = None
    path: Sequence[str] = field(default_factory=list)
    depth: int = 0
    settings_items_priorities: dict[str, int] = field(default_factory=dict)
    is_recording: bool = False
    recorded_sequence: list[BaseAction] = field(default_factory=list)
