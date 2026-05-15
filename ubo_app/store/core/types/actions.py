"""Action types for the core store module."""

from __future__ import annotations

from dataclasses import field
from typing import TYPE_CHECKING

from redux import BaseAction

from ubo_app.utils.service import ServiceUnavailableError

if TYPE_CHECKING:
    from ubo_app.store.core.types.enums import MenuScrollDirection, SettingsCategory
    from ubo_app.store.core.types.status_bar import StatusBarData
    from ubo_app.store.core.types.view_data import MenuItemData, ViewData
    from ubo_app.store.ubo_actions import BasicType


def service_default_factory() -> str | None:
    """Get the current service ID for action attribution."""
    from ubo_app.utils.service import get_service

    try:
        return get_service().service_id
    except ServiceUnavailableError:
        return None


class MainAction(BaseAction):
    """Base class for main store actions."""


class UpdateLightDMState(MainAction):
    """Action for updating LightDM state."""

    is_active: bool
    is_enable: bool


class RegisterAppAction(MainAction):
    """Base class for app registration actions.

    All fields are serializable (no callables or Menu objects).
    Services register action handlers in the action_registry separately.
    """

    label: str
    icon: str = ''
    action_id: str | None = None
    background_color: str | None = None
    service: str | None = field(default_factory=service_default_factory)
    key: str | None = None


class RegisterRegularAppAction(RegisterAppAction):
    """Action to register a regular app in the Apps menu."""

    priority: int | None = None
    app_category: str | None = None


class DeregisterRegularAppAction(MainAction):
    """Action to deregister a regular app from the Apps menu."""

    service: str | None = field(default_factory=service_default_factory)
    key: str | None = None


class RegisterSettingAppAction(RegisterAppAction):
    """Action to register a settings app in a category."""

    category: SettingsCategory
    priority: int | None = None


class PowerAction(MainAction):
    """Base class for power actions."""


class PowerOffAction(PowerAction):
    """Action to power off the device."""


class RebootAction(PowerAction):
    """Action to reboot the device."""


class SetAreEnclosuresVisibleAction(MainAction):
    """Action to set header/footer visibility."""

    is_header_visible: bool = True
    is_footer_visible: bool = True


# =============================================================================
# Menu Navigation Actions
# =============================================================================


class MenuAction(MainAction):
    """Base class for menu navigation actions."""


class MenuGoBackAction(MenuAction):
    """Action to navigate back in the menu."""


class MenuGoHomeAction(MenuAction):
    """Action to navigate to the home screen."""


class MenuChooseByIconAction(MenuAction):
    """Action to choose a menu item by icon."""

    icon: str


class MenuChooseByLabelAction(MenuAction):
    """Action to choose a menu item by label."""

    label: str


class MenuChooseByIndexAction(MenuAction):
    """Action to choose a menu item by index."""

    index: int


class MenuScrollAction(MenuAction):
    """Action to scroll the menu."""

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


class StackPushRenderAction(StackAction):
    """Push a generic reusable render view onto the navigation stack."""

    kind: str
    title: str = ''
    props: dict[
        str,
        BasicType | tuple[BasicType, ...] | list[BasicType],
    ] = field(default_factory=dict)
    items: tuple[MenuItemData, ...] = ()
    stream_id: str = ''


class StackPushNotificationAction(StackAction):
    """Push a notification overlay onto the navigation stack.

    Idempotent: if a notification with the same ``notification_id`` is
    already on the stack, the reducer leaves it in place rather than
    pushing a duplicate.
    """

    notification_id: str


class StackPopNotificationAction(StackAction):
    """Pop a notification overlay from the navigation stack by id.

    Removes the ``NotificationStackItem`` whose ``notification_id``
    matches. No-op when the notification isn't on the stack. Unlike
    ``StackPopItemAction`` (which keys on the stack item's UUID, forcing
    callers to read the stack first and risk acting on a stale view),
    this is evaluated entirely at reducer time against current state.
    """

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


class UpdateApplicationKwargsAction(StackAction):
    """Update initialization_kwargs of a running ApplicationStackItem.

    Finds the application by application_id in the stack and merges
    the provided kwargs into its initialization_kwargs.
    """

    application_id: str
    kwargs: dict[
        str,
        BasicType | tuple[BasicType, ...] | list[BasicType],
    ] = field(default_factory=dict)


class UpdateRenderPropsAction(StackAction):
    """Merge props into an open generic render view by kind or stream_id."""

    kind: str = ''
    stream_id: str = ''
    next_kind: str = ''
    title: str = ''
    props: dict[
        str,
        BasicType | tuple[BasicType, ...] | list[BasicType],
    ] = field(default_factory=dict)


class UpdatePromptAction(StackAction):
    """Update an open prompt view's icon, prompt text, or action items."""

    title: str = ''
    prompt: str = ''
    icon: str = ''
    items: tuple[MenuItemData, ...] | None = None


# =============================================================================
# Dynamic Menu Actions (Services update menu content via Redux)
# =============================================================================


class DynamicMenuAction(MainAction):
    """Base class for dynamic menu actions."""


class UpdateDynamicMenuAction(DynamicMenuAction):
    """Update or create a dynamic menu's content.

    Services dispatch this to provide menu items computed from their state.
    This replaces the pattern of returning HeadlessMenu from autoruns.

    Example::

        @store.autorun(lambda state: state.wifi.connections)
        def update_wifi_menu(connections):
            items = tuple(
                MenuItemData(
                    key=c.ssid,
                    label=c.ssid,
                    icon='...',
                    action_id=f'wifi:open:{c.ssid}',
                )
                for c in (connections or [])
            )
            store.dispatch(UpdateDynamicMenuAction(
                menu_id='wifi:connections',
                title='Wi-Fi',
                items=items,
                placeholder='No connections found',
            ))

    """

    menu_id: str  # Unique menu identifier
    title: str = ''
    heading: str | None = None
    sub_heading: str | None = None
    items: tuple[MenuItemData | None, ...] = ()
    placeholder: str = ''


class ClearDynamicMenuAction(DynamicMenuAction):
    """Remove a dynamic menu from the state.

    Used when a menu is no longer needed (e.g., service stopped).
    """

    menu_id: str


class ExecuteMenuActionAction(MainAction):
    """Execute a menu action by its action_id.

    This action triggers the execution of a registered action handler.
    Services register handlers via action_registry.register_action().
    The UI dispatches this when a menu item with an action_id is selected.

    If menu_key is provided and the handler returns a non-None result
    (e.g., a Menu), the reducer will push the menu_key onto the stack.
    """

    action_id: str
    menu_key: str | None = None


class OpenApplicationAction(MainAction):
    """Action to open an application."""

    application_id: str
    initialization_args: tuple[BasicType, ...] = ()
    initialization_kwargs: dict[
        str,
        BasicType | tuple[BasicType, ...] | list[BasicType],
    ] = field(default_factory=dict)


class OpenRenderAction(MainAction):
    """Action to open a generic reusable render view."""

    kind: str
    title: str = ''
    props: dict[
        str,
        BasicType | tuple[BasicType, ...] | list[BasicType],
    ] = field(default_factory=dict)
    items: tuple[MenuItemData, ...] = ()
    stream_id: str = ''


class CloseApplicationAction(MainAction):
    """Action to close an application."""

    application_instance_id: str


class StackPushInstructionAction(MainAction):
    """Push an instruction/waiting view onto the stack."""

    title: str = ''
    instruction: str = ''
    icon: str = ''
    spinner: bool = False
    timeout_seconds: int = 0
    footer_text: str = ''


class CloseInstructionAction(MainAction):
    """Close an instruction view by its stack item ID."""

    instruction_id: str


class UpdateInstructionProgressAction(MainAction):
    """Update the progress text of an instruction view."""

    instruction_id: str
    progress_text: str = ''


class StackPushPromptAction(MainAction):
    """Push a prompt/confirmation view onto the stack."""

    title: str = ''
    prompt: str = ''
    icon: str = ''
    items: tuple[MenuItemData, ...] = ()


class UpdateCurrentViewAction(MainAction):
    """Update current_view with a computed view (used by dynamic menu system)."""

    view: ViewData
    status_bar: StatusBarData | None = None


class ToggleRecordingAction(MainAction):
    """Action for toggling recording."""


class ReplayRecordedSequenceAction(MainAction):
    """Action for replaying a recorded sequence."""


class ReportReplayingDoneAction(MainAction):
    """Action for reporting that replaying is done."""


class TakeScreenshotAction(MainAction):
    """Action to request a screenshot from the GUI client."""


class ScreenshotDataAction(MainAction):
    """Action dispatched by GUI client with captured screenshot data."""

    data: bytes
    hash: str
