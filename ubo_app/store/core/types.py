# ruff: noqa: D100, D101, D103
from __future__ import annotations

from dataclasses import field
from enum import StrEnum
from typing import TYPE_CHECKING

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


# =============================================================================
# Stack Item Types for Redux State
# =============================================================================
# These are serializable representations of the navigation stack.
# Unlike ubo_gui's StackItem classes which hold object references (Menu, PageWidget),
# these use IDs to enable Redux serialization and single source of truth.


class MenuStackItem(Immutable):
    """Redux representation of a menu in the navigation stack.

    Attributes
    ----------
    id : str
        Unique identifier for this stack item instance.
    menu_key : str
        Key of the menu item used to navigate here (e.g., 'main', 'settings', 'wifi').
        For root menu, this is empty string.
    page_index : int
        Current page index within the menu (0-indexed).

    """

    id: str  # Unique stack item ID
    menu_key: str  # Key used to navigate here
    page_index: int = 0


class ApplicationStackItem(Immutable):
    """Redux representation of an application in the navigation stack.

    Attributes
    ----------
    id : str
        Unique identifier for this stack item instance.
    application_id : str
        Registered application ID (e.g., 'camera:viewfinder').
    initialization_args : tuple
        Arguments passed when opening the application.
    initialization_kwargs : dict
        Keyword arguments passed when opening the application.

    """

    id: str  # Unique stack item ID
    application_id: str  # Registered application ID
    initialization_args: tuple[BasicType, ...] = ()
    initialization_kwargs: dict[
        str,
        BasicType | tuple[BasicType, ...] | list[BasicType],
    ] = field(default_factory=dict)


class NotificationStackItem(Immutable):
    """Redux representation of a notification overlay in the navigation stack.

    Attributes
    ----------
    id : str
        Unique identifier for this stack item instance.
    notification_id : str
        ID of the notification being displayed.

    """

    id: str  # Unique stack item ID
    notification_id: str  # ID of the notification


# Type alias for any stack item
StackItemType = MenuStackItem | ApplicationStackItem | NotificationStackItem


SETTINGS_ICONS = {
    SettingsCategory.NETWORK: '󰛳',
    SettingsCategory.REMOTE: '󰑔',
    SettingsCategory.SYSTEM: '󰒔',
    SettingsCategory.HARDWARE: '',
    SettingsCategory.ASSISTANT: '󰚩',
    SettingsCategory.DOCKER: '󰡨',
    SettingsCategory.ACCESSIBILITY: '󰙋',
}


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


# =============================================================================
# Stack Management Actions (Redux controls navigation state)
# =============================================================================


class StackAction(MainAction):
    """Base class for stack manipulation actions."""


class StackPushMenuAction(StackAction):
    """Push a menu onto the navigation stack.

    This should be dispatched when navigating into a sub-menu.
    """

    menu_key: str  # Key of the SubMenuItem that was selected


class StackPushApplicationAction(StackAction):
    """Push an application onto the navigation stack.

    This should be dispatched when opening an application.
    """

    application_id: str
    initialization_args: tuple[BasicType, ...] = ()
    initialization_kwargs: dict[
        str,
        BasicType | tuple[BasicType, ...] | list[BasicType],
    ] = field(default_factory=dict)


class StackPushNotificationAction(StackAction):
    """Push a notification overlay onto the navigation stack."""

    notification_id: str


class StackPopAction(StackAction):
    """Pop the top item from the navigation stack.

    Optionally pop multiple items by specifying count.
    """

    count: int = 1  # Number of items to pop


class StackPopToRootAction(StackAction):
    """Pop all items except root, returning to home screen."""


class StackPopItemAction(StackAction):
    """Pop a specific item from the stack by its ID.

    Used for closing specific applications or notifications.
    """

    item_id: str  # ID of the stack item to remove


class StackSetPageIndexAction(StackAction):
    """Set the page index of the current menu.

    Only valid when the top of stack is a MenuStackItem.
    """

    page_index: int


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


# =============================================================================
# Stack Change Events (GUI subscribes to these for rendering)
# =============================================================================


class StackChangedEvent(MainEvent):
    """Emitted when the navigation stack changes.

    The GUI should update its display based on the new stack state.
    """

    stack: tuple[StackItemType, ...]


class StackPageIndexChangedEvent(MainEvent):
    """Emitted when the page index of the current menu changes."""

    page_index: int


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
    # New: Full navigation stack as source of truth
    stack: tuple[StackItemType, ...] = ()
    # Legacy: These are derived from stack for backward compatibility
    path: Sequence[str] = field(default_factory=list)
    depth: int = 0
    is_header_visible: bool = True
    is_footer_visible: bool = True
    apps_items_priorities: dict[str, int] = field(default_factory=dict)
    settings_items_priorities: dict[str, int] = field(default_factory=dict)
    is_recording: bool = False
    is_replaying: bool = False
    recorded_sequence: list[BaseAction] = field(default_factory=list)
