"""View data types for the dumb UI architecture.

These types describe what the UI should render. The reducer computes these
from the stack and other state. The UI layer receives this data and renders it.
This enables multi-client support (Apple Watch, Web UI, MCU).
"""

from __future__ import annotations

from dataclasses import field
from typing import TYPE_CHECKING, Literal, TypeAlias

from immutable import Immutable

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ubo_app.store.ubo_actions import BasicType


class MenuItemData(Immutable):
    """Serializable representation of a menu item for rendering.

    This is what the UI receives to render a menu item.
    Clicking dispatches the action_id if provided.
    """

    key: str  # Unique key for this item
    label: str  # Display label
    icon: str  # Icon character/code
    color: str = '#ffffff'  # Icon/label color
    is_short: bool = False  # Whether to use short display mode
    action_id: str | None = None  # Action to dispatch on click (if any)
    background_color: str | None = None  # Optional background color


class HomeViewData(Immutable):
    """Data for rendering the home screen view.

    Home screen includes: menu items, CPU/RAM gauges, volume level.
    """

    type: Literal['home'] = 'home'
    show_status_bar: bool = True
    menu_items: tuple[MenuItemData, ...] = ()  # Main, Notifications, Power
    cpu_percent: float = 50.0
    ram_percent: float = 50.0
    volume_level: float = 0.0  # 0.0-1.0


class MenuViewData(Immutable):
    """Data for rendering a menu view.

    Standard menu with title, items, and pagination.
    For HeadedMenu, includes heading and sub_heading.
    """

    type: Literal['menu'] = 'menu'
    show_status_bar: bool = True  # Based on page_index == 0
    title: str = ''
    heading: str | None = None  # Optional heading (for HeadedMenu)
    sub_heading: str | None = None  # Optional sub-heading (for HeadedMenu)
    items: tuple[MenuItemData | None, ...] = ()  # Items for current page
    placeholder: str | None = None  # Text shown when items is empty
    page_index: int = 0
    total_pages: int = 1
    stack_depth: int = 1  # Navigation stack depth (for push/pop animation)


class ApplicationViewData(Immutable):
    """Data for rendering an application view.

    Applications are rendered by their own widget classes.
    """

    type: Literal['application'] = 'application'
    show_status_bar: bool = False
    application_id: str = ''
    extra_data: Mapping[
        str,
        BasicType | tuple[BasicType, ...] | list[BasicType],
    ] = field(default_factory=dict)
    stack_depth: int = 1  # Navigation stack depth (for push/pop animation)


class NotificationViewData(Immutable):
    """Data for rendering a notification overlay view."""

    type: Literal['notification'] = 'notification'
    show_status_bar: bool = False
    notification_id: str = ''
    title: str = ''
    content: str = ''
    icon: str = ''
    color: str = '#ffffff'
    items: tuple[MenuItemData | None, ...] = ()  # Action items (camera, web UI, etc.)
    extra_information: str = ''  # Additional info shown when "i" button is pressed
    stack_depth: int = 1  # Navigation stack depth (for push/pop animation)


# Union type for all view data types
ViewData: TypeAlias = (
    HomeViewData | MenuViewData | ApplicationViewData | NotificationViewData
)
