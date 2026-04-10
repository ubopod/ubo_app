"""Event types for the core store module."""

from __future__ import annotations

from typing import TYPE_CHECKING

from redux import BaseEvent

if TYPE_CHECKING:
    from ubo_app.store.core.types.stack_items import StackItemType
    from ubo_app.store.core.types.status_bar import StatusBarData
    from ubo_app.store.core.types.view_data import ViewData
    from ubo_app.store.services.keypad import KeypadAction


class MainEvent(BaseEvent):
    """Base class for main store events."""


class InitEvent(MainEvent):
    """Event emitted when the store is initialized."""


class MenuEvent(MainEvent):
    """Base class for menu events."""


class MenuChooseByIconEvent(MenuEvent):
    """Event emitted when choosing by icon."""

    icon: str


class MenuChooseByLabelEvent(MenuEvent):
    """Event emitted when choosing by label."""

    label: str


class MenuChooseByIndexEvent(MenuEvent):
    """Event emitted when choosing by index."""

    index: int


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


class ViewChangedEvent(MainEvent):
    """Emitted when the current view data changes.

    The UI should re-render based on this new view data.
    This is the primary event for the dumb UI architecture.
    """

    view: ViewData
    status_bar: StatusBarData | None = None


class DynamicMenuChangedEvent(MainEvent):
    """Emitted when a dynamic menu's content changes.

    This triggers view recomputation if the changed menu is currently visible.
    """

    menu_id: str


class PowerEvent(MainEvent):
    """Base class for power events."""


class PowerOffEvent(PowerEvent):
    """Event emitted for power off."""


class RebootEvent(PowerEvent):
    """Event emitted for reboot."""


class ScreenshotEvent(MainEvent):
    """Event for taking a screenshot."""


class SnapshotEvent(MainEvent):
    """Event for taking a snapshot of the store."""


class StoreRecordedSequenceEvent(MainEvent):
    """Event for storing a recorded sequence."""

    recorded_sequence: tuple[KeypadAction, ...]


class ExecuteMenuActionEvent(MainEvent):
    """Event for executing a menu action by its action_id.

    Emitted by the reducer when an ExecuteMenuActionAction is dispatched.
    The event handler layer calls execute_action() and optionally pushes
    a menu onto the stack if the handler returns a result.
    """

    action_id: str
    menu_key: str | None = None


class ReplayRecordedSequenceEvent(MainEvent):
    """Event for replaying a recorded sequence."""


class ApplicationScrollEvent(MainEvent):
    """Event emitted when scrolling on an application view.

    The GUI client subscribes to this event to invoke local go_up/go_down
    on the current application widget (e.g. image viewer zoom/scroll).
    """

    direction: str  # 'up' or 'down'


class ScreenshotDataEvent(MainEvent):
    """Event emitted when screenshot data is received from GUI client."""

    data: bytes
    hash: str
