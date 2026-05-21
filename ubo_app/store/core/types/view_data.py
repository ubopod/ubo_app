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
    # All menu items (GUI handles per-page slicing)
    items: tuple[MenuItemData | None, ...] = ()
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


class RenderViewData(Immutable):
    """Data for rendering a generic reusable view.

    This is the preferred path for UI that can be expressed with shared
    widgets such as QR codes, text/image viewers, status pages, or streams.
    ApplicationViewData remains available for custom views that do not fit a
    generic widget yet.
    """

    type: Literal['render'] = 'render'
    show_status_bar: bool = False
    kind: str = ''
    title: str = ''
    props: Mapping[
        str,
        BasicType | tuple[BasicType, ...] | list[BasicType],
    ] = field(default_factory=dict)
    items: tuple[MenuItemData, ...] = ()
    stream_id: str = ''
    stack_depth: int = 1


class ChatBubbleData(Immutable):
    """Fully-resolved representation of one chat speech bubble.

    Everything the renderer needs to draw the bubble is precomputed here by
    ``get_chat_view_data`` — alignment, colors, the L1/L2/L3 pointer binding,
    and (for audio bubbles) the waveform. The rendering layer contains no
    conversation logic; it only draws what this describes.
    """

    message_id: str = ''
    role: str = 'assistant'  # 'user' | 'assistant'
    alignment: str = 'left'  # 'left' (assistant) | 'right' (user)
    kind: str = 'text'  # 'text' | 'audio'
    text: str = ''
    color: str = '#ffffff'  # foreground (text / waveform) color
    background_color: str = '#2b2f38'  # bubble fill color
    pointer_key: str = ''  # '' | 'L1' | 'L2' | 'L3' — bound hardware button
    is_playing: bool = False  # audio bubble currently playing
    waveform: tuple[float, ...] = ()  # normalized (0..1) bar heights


class ChatViewData(Immutable):
    """Data for rendering the chat overlay view.

    The store computes this from the ``chat`` slice and the ``ChatStackItem``
    scroll position. ``items`` holds up to three ``MenuItemData`` entries
    (index 0 → L1, 1 → L2, 2 → L3) so an L1/L2/L3 press routes to the bubble
    bound to that button.
    """

    type: Literal['chat'] = 'chat'
    show_status_bar: bool = False
    bubbles: tuple[ChatBubbleData, ...] = ()
    items: tuple[MenuItemData, ...] = ()  # L1/L2/L3 button bindings
    scroll_offset: int = 0  # bubbles scrolled back from the newest
    total_bubbles: int = 0
    stack_depth: int = 1


class NotificationViewData(Immutable):
    """Data for rendering a notification overlay view."""

    type: Literal['notification'] = 'notification'
    show_status_bar: bool = False
    notification_id: str = ''
    title: str = ''
    content: str = ''
    icon: str = ''
    color: str = '#ffffff'
    # All notification action items (pagination handled by renderer)
    items: tuple[MenuItemData | None, ...] = ()
    extra_information: str = ''  # Additional info shown when "i" button is pressed
    page_index: int = 0
    total_pages: int = 1
    stack_depth: int = 1  # Navigation stack depth (for push/pop animation)


class InstructionViewData(Immutable):
    """Data for rendering an instruction/waiting view.

    Shows instructions to the user and waits for an external event
    (e.g., IR signal received, QR code scanned). Has optional timeout.
    Reusable across services — not specific to any one feature.
    """

    type: Literal['instruction'] = 'instruction'
    show_status_bar: bool = False
    title: str = ''
    instruction: str = ''
    icon: str = ''
    spinner: bool = False
    timeout_seconds: int = 0
    progress_text: str = ''
    footer_text: str = ''
    stack_depth: int = 1


class PromptViewData(Immutable):
    """Data for rendering a confirmation/prompt view.

    Shows a prompt with action buttons. Generalizes the 2-button
    confirmation pattern (Yes/Cancel, Connect/Delete, etc.).
    Reusable across services — not specific to any one feature.
    """

    type: Literal['prompt'] = 'prompt'
    show_status_bar: bool = False
    title: str = ''
    prompt: str = ''
    icon: str = ''
    items: tuple[MenuItemData, ...] = ()
    stack_depth: int = 1


# Union type for all view data types
ViewData: TypeAlias = (
    HomeViewData
    | MenuViewData
    | ApplicationViewData
    | NotificationViewData
    | InstructionViewData
    | PromptViewData
    | RenderViewData
    | ChatViewData
)
