"""Platform-agnostic UI data models for store-driven rendering."""

from __future__ import annotations

from dataclasses import field
from enum import StrEnum
from typing import Any

from immutable import Immutable


class RenderedItemType(StrEnum):
    """Type of rendered menu item."""

    ACTION = 'action'
    SUBMENU = 'submenu'
    APPLICATION = 'application'
    DIVIDER = 'divider'
    EMPTY = 'empty'


class RenderedItem(Immutable):
    """Serializable menu item for any UI platform.

    This is a platform-agnostic representation of a menu item that can be
    serialized to gRPC and rendered by any client (Kivy, web, iOS, LVGL, etc).
    """

    type: RenderedItemType = RenderedItemType.ACTION
    key: str | None = None
    label: str = ''
    icon: str = ''
    color: str = '#FFFFFF'
    background_color: str | None = None
    is_short: bool = False
    is_disabled: bool = False
    progress: float | None = None
    opacity: float = 1.0


class RenderedPage(Immutable):
    """A page of items ready for display.

    Contains all the information needed to render a menu page,
    including pagination state and navigation context.
    """

    items: tuple[RenderedItem | None, ...] = ()
    title: str = ''
    page_index: int = 0
    total_pages: int = 1
    can_go_up: bool = False
    can_go_down: bool = False
    breadcrumb: tuple[str, ...] = ()


class RenderedApplication(Immutable):
    """Serializable application state.

    Represents an open application with its content as structured data.
    The content dict is intentionally generic to allow flexibility per app type.
    """

    application_id: str = ''
    instance_id: str = ''
    title: str = ''
    content: dict[str, Any] = field(default_factory=dict)


class RenderedView(Immutable):
    """Complete view state for rendering.

    This is the top-level structure that a client receives to render the UI.
    It contains either a menu page or an application, plus overall navigation state.
    """

    # Current view type
    is_menu: bool = True
    is_application: bool = False

    # Menu view (when is_menu is True)
    page: RenderedPage | None = None

    # Application view (when is_application is True)
    application: RenderedApplication | None = None

    # Navigation state
    stack_depth: int = 0
    is_at_home: bool = True
    can_go_back: bool = False

    # Header/footer visibility
    is_header_visible: bool = True
    is_footer_visible: bool = True
