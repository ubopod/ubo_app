"""View data types for the dumb UI architecture.

These types describe what the UI should render. The reducer computes these
from the stack and other state. The UI layer receives this data and renders it.
This enables multi-client support (Apple Watch, Web UI, MCU).
"""

from __future__ import annotations

from dataclasses import field
from typing import TypeAlias

from immutable import Immutable


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

    type: str = 'home'  # Literal discriminator
    show_status_bar: bool = True
    menu_items: tuple[MenuItemData, ...] = ()  # Main, Notifications, Power
    cpu_percent: float = 0.0
    ram_percent: float = 0.0
    volume_level: float = 0.0  # 0.0-1.0


class MenuViewData(Immutable):
    """Data for rendering a menu view.

    Standard menu with title, items, and pagination.
    """

    type: str = 'menu'  # Literal discriminator
    show_status_bar: bool = True  # Based on page_index == 0
    title: str = ''
    items: tuple[MenuItemData | None, ...] = ()  # Items for current page
    page_index: int = 0
    total_pages: int = 1


class ApplicationViewData(Immutable):
    """Data for rendering an application view.

    Applications are rendered by their own widget classes.
    """

    type: str = 'application'  # Literal discriminator
    show_status_bar: bool = False
    application_id: str = ''
    extra_data: dict[str, str] = field(default_factory=dict)  # e.g., {'text': '...'}


class NotificationViewData(Immutable):
    """Data for rendering a notification overlay view."""

    type: str = 'notification'  # Literal discriminator
    show_status_bar: bool = False
    notification_id: str = ''
    title: str = ''
    content: str = ''
    icon: str = ''
    color: str = '#ffffff'


# Union type for all view data types
ViewData: TypeAlias = (
    HomeViewData | MenuViewData | ApplicationViewData | NotificationViewData
)
