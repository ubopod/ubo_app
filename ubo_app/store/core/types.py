# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from dataclasses import field
from enum import StrEnum
from typing import TYPE_CHECKING

from immutable import Immutable
from redux import BaseAction, BaseEvent

from ubo_app.utils.service import ServiceUnavailableError


class SettingsCategory(StrEnum):
    NETWORK = 'Network'
    REMOTE = 'Remote'
    SYSTEM = 'System'
    HARDWARE = 'Hardware'
    SPEECH = 'Speech'
    DOCKER = 'Docker'


class MenuScrollDirection(StrEnum):
    UP = 'up'
    DOWN = 'down'


SETTINGS_ICONS = {
    SettingsCategory.NETWORK: '󰛳',
    SettingsCategory.REMOTE: '󰑔',
    SettingsCategory.SYSTEM: '󰒔',
    SettingsCategory.HARDWARE: '',
    SettingsCategory.SPEECH: '󰔊',
    SettingsCategory.DOCKER: '󰡨',
}


if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_gui.menu.types import Item, Menu


class MainAction(BaseAction): ...


class UpdateLightDMState(MainAction):
    is_active: bool
    is_enable: bool


def service_default_factory() -> str | None:
    from ubo_app.utils.service import get_service

    try:
        return get_service().service_id
    except ServiceUnavailableError:
        return None


class RegisterAppAction(MainAction):
    menu_item: Item
    service: str | None = field(default_factory=service_default_factory)
    key: str | None = None


class RegisterRegularAppAction(RegisterAppAction):
    priority: int | None = None


class DeregisterRegularAppAction(MainAction):
    service: str | None = field(default_factory=service_default_factory)
    key: str | None = None


class RegisterSettingAppAction(RegisterAppAction):
    category: SettingsCategory
    priority: int | None = None


class PowerAction(MainAction): ...


class PowerOffAction(PowerAction): ...


class RebootAction(PowerAction): ...


class SetMenuPathAction(MainAction):
    path: Sequence[str]
    depth: int


class SetAreEnclosuresVisibleAction(MainAction):
    is_header_visible: bool = True
    is_footer_visible: bool = True


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
    application_id: str
    initialization_args: tuple = ()
    initialization_kwargs: dict = field(default_factory=dict)


class CloseApplicationAction(MainAction):
    application_instance_id: str


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
    application_id: str
    initialization_args: tuple = ()
    initialization_kwargs: dict = field(default_factory=dict)


class CloseApplicationEvent(MainEvent):
    application_instance_id: str


class PowerEvent(MainEvent): ...


class PowerOffEvent(PowerEvent): ...


class RebootEvent(PowerEvent): ...


class ScreenshotEvent(MainEvent):
    """Event for taking a screenshot."""


class SnapshotEvent(MainEvent):
    """Event for taking a snapshot of the store."""


class ToggleRecordingAction(MainAction):
    """Action for toggling recording."""


class StoreRecordedSequenceEvent(MainEvent):
    """Event for storing a recorded sequence."""

    recorded_sequence: list[BaseAction]


class ReplayRecordedSequenceAction(MainAction):
    """Action for replaying a recorded sequence."""


class ReplayRecordedSequenceEvent(MainEvent):
    """Event for replaying a recorded sequence."""


class ReportReplayingDoneAction(MainAction):
    """Action for reporting that replaying is done."""


class MainState(Immutable):
    menu: Menu | None = None
    path: Sequence[str] = field(default_factory=list)
    depth: int = 0
    is_header_visible: bool = True
    is_footer_visible: bool = True
    apps_items_priorities: dict[str, int] = field(default_factory=dict)
    settings_items_priorities: dict[str, int] = field(default_factory=dict)
    is_recording: bool = False
    is_replaying: bool = False
    recorded_sequence: list[BaseAction] = field(default_factory=list)
