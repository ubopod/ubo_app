"""Stack item types for Redux navigation state.

These are serializable representations of the navigation stack.
Unlike ubo_gui's StackItem classes which hold object references (Menu, PageWidget),
these use IDs to enable Redux serialization and single source of truth.
"""

from __future__ import annotations

from dataclasses import field
from typing import TYPE_CHECKING, TypeAlias

from immutable import Immutable

if TYPE_CHECKING:
    from ubo_app.store.core.types.view_data import MenuItemData
    from ubo_app.store.ubo_actions import BasicType


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


class RenderStackItem(Immutable):
    """Redux representation of a generic reusable render view."""

    id: str
    kind: str
    title: str = ''
    props: dict[
        str,
        BasicType | tuple[BasicType, ...] | list[BasicType],
    ] = field(default_factory=dict)
    items: tuple[MenuItemData, ...] = ()
    stream_id: str = ''


class ChatStackItem(Immutable):
    """Redux representation of the chat overlay in the navigation stack.

    The conversation itself lives in the ``chat`` slice — this item only
    references the session and holds the scroll position, exactly how
    ``NotificationStackItem`` references ``state.notifications``.

    Attributes
    ----------
    id : str
        Unique identifier for this stack item instance.
    session_id : str
        ID of the chat session being displayed.
    scroll_offset : int
        How many bubbles the view is scrolled back from the newest (0 =
        newest message bound to L3).

    """

    id: str
    session_id: str = ''
    scroll_offset: int = 0


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
    page_index: int = 0


class InstructionStackItem(Immutable):
    """Redux representation of an instruction/waiting view in the navigation stack.

    Shows instructions and waits for an external event (e.g., IR registration).
    """

    id: str
    title: str = ''
    instruction: str = ''
    icon: str = ''
    spinner: bool = False
    timeout_seconds: int = 0
    progress_text: str = ''
    footer_text: str = ''


class PromptStackItem(Immutable):
    """Redux representation of a prompt/confirmation view in the navigation stack.

    Shows a prompt with action buttons (e.g., Yes/Cancel).
    """

    id: str
    title: str = ''
    prompt: str = ''
    icon: str = ''
    items: tuple[MenuItemData, ...] = ()


# Type alias for any stack item
StackItemType: TypeAlias = (
    MenuStackItem
    | ApplicationStackItem
    | RenderStackItem
    | NotificationStackItem
    | InstructionStackItem
    | PromptStackItem
    | ChatStackItem
)
