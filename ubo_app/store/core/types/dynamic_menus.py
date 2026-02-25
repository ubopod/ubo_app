"""Dynamic menu types for decoupled UI architecture.

These types allow services to provide menu content via Redux actions,
rather than returning ubo-gui types directly from autoruns.
This enables serialization and multi-client support.
"""

from __future__ import annotations

from dataclasses import field
from typing import TYPE_CHECKING

from immutable import Immutable

if TYPE_CHECKING:
    from ubo_app.store.core.types.view_data import MenuItemData


class DynamicMenuData(Immutable):
    """Serializable representation of a dynamic menu's content.

    Services dispatch UpdateDynamicMenuAction to provide menu content.
    The reducer stores this in DynamicMenusState.
    View computation uses this when rendering menus.
    """

    menu_id: str  # Unique menu identifier (e.g., 'wifi:connections')
    title: str = ''  # Menu title
    heading: str | None = None  # Optional heading (for HeadedMenu style)
    sub_heading: str | None = None  # Optional sub-heading
    items: tuple[MenuItemData | None, ...] = ()  # Menu items (None = empty slot)
    placeholder: str = ''  # Text to show when items is empty


class DynamicMenusState(Immutable):
    """State slice containing all dynamic menus.

    This is the Redux state that holds computed menu content from services.
    When a service's state changes, its autorun dispatches UpdateDynamicMenuAction
    to update the relevant menu here.

    The ``version`` counter increments on every update or clear, enabling
    efficient change detection in autorun selectors (compare one integer
    instead of rebuilding tuple representations of all menus).  Note that
    multiple menu updates within the same reducer tick share one version
    bump — the counter signals "something changed", not per-menu versions.
    """

    menus: dict[str, DynamicMenuData] = field(default_factory=dict)
    version: int = 0
