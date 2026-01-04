# ruff: noqa: D100, D101, D103
from __future__ import annotations

from dataclasses import field
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import uuid4

from immutable import Immutable
from redux import BaseAction, BaseEvent

from ubo_app.utils.service import ServiceUnavailableError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_gui.menu.types import Item, Menu

    from ubo_app.store.ubo_actions import BasicType


class SettingsCategory(StrEnum):
    NETWORK = 'Network'
    REMOTE = 'Remote'
    SYSTEM = 'System'
    HARDWARE = 'Hardware'
    ASSISTANT = 'Assistant'
    DOCKER = 'Docker'
    ACCESSIBILITY = 'Accessibility'


class MenuScrollDirection(StrEnum):
    UP = 'up'
    DOWN = 'down'


class StackItemType(StrEnum):
    """Type of item in the navigation stack."""

    MENU = 'menu'
    APPLICATION = 'application'


SETTINGS_ICONS = {
    SettingsCategory.NETWORK: '󰛳',
    SettingsCategory.REMOTE: '󰑔',
    SettingsCategory.SYSTEM: '󰒔',
    SettingsCategory.HARDWARE: '',
    SettingsCategory.ASSISTANT: '󰚩',
    SettingsCategory.DOCKER: '󰡨',
    SettingsCategory.ACCESSIBILITY: '󰙋',
}


# Navigation Stack Types


class StackItem(Immutable):
    """Base item in the navigation stack."""

    type: StackItemType
    key: str | None = None
    title: str = ''


class MenuStackItem(StackItem):
    """Stack item for a menu level."""

    type: StackItemType = StackItemType.MENU
    menu_path: tuple[str, ...] = ()
    page_index: int = 0


def _generate_instance_id() -> str:
    return str(uuid4())


class ApplicationStackItem(StackItem):
    """Stack item for an open application."""

    type: StackItemType = StackItemType.APPLICATION
    application_id: str = ''
    instance_id: str = field(default_factory=_generate_instance_id)
    initialization_args: tuple[BasicType, ...] = ()
    initialization_kwargs: dict[
        str,
        BasicType | tuple[BasicType, ...] | list[BasicType],
    ] = field(default_factory=dict)


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


# Navigation Stack Actions


class NavigatePushMenuAction(MenuAction):
    """Push a menu onto the navigation stack."""

    item_key: str
    title: str = ''


class NavigatePopAction(MenuAction):
    """Pop one level from the navigation stack."""


class NavigateClearAction(MenuAction):
    """Clear stack to root (go home)."""


class SetPageIndexAction(MenuAction):
    """Update scroll position in current menu."""

    page_index: int


class PushApplicationAction(MenuAction):
    """Push an application onto the navigation stack."""

    application_id: str
    instance_id: str = field(default_factory=_generate_instance_id)
    title: str = ''
    initialization_args: tuple[BasicType, ...] = ()
    initialization_kwargs: dict[
        str,
        BasicType | tuple[BasicType, ...] | list[BasicType],
    ] = field(default_factory=dict)


class PopApplicationAction(MenuAction):
    """Pop application by instance_id from stack."""

    instance_id: str


class OpenApplicationAction(MainAction):
    application_id: str
    initialization_args: tuple[BasicType, ...] = ()
    initialization_kwargs: dict[
        str,
        BasicType | tuple[BasicType, ...] | list[BasicType],
    ] = field(default_factory=dict)


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
    initialization_args: tuple[BasicType, ...] = ()
    initialization_kwargs: dict[
        str,
        BasicType | tuple[BasicType, ...] | list[BasicType],
    ] = field(default_factory=dict)


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
    navigation_stack: tuple[StackItem, ...] = ()
    path: Sequence[str] = field(default_factory=list)
    depth: int = 0
    is_header_visible: bool = True
    is_footer_visible: bool = True
    apps_items_priorities: dict[str, int] = field(default_factory=dict)
    settings_items_priorities: dict[str, int] = field(default_factory=dict)
    is_recording: bool = False
    is_replaying: bool = False
    recorded_sequence: list[BaseAction] = field(default_factory=list)

