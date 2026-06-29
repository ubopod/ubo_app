"""Main state type for the core store module."""

from __future__ import annotations

from dataclasses import field
from typing import TYPE_CHECKING

from immutable import Immutable

if TYPE_CHECKING:
    from ubo_app.store.core.types.stack_items import StackItemType
    from ubo_app.store.core.types.status_bar import StatusBarData
    from ubo_app.store.core.types.view_data import ViewData
    from ubo_app.store.services.keypad import KeypadAction


class RegisteredAppEntry(Immutable):
    """Serializable record of a registered app or setting."""

    key: str
    label: str
    icon: str
    action_id: str | None = None
    background_color: str | None = None
    priority: int | None = None
    category: str | None = None  # SettingsCategory value, None for regular apps
    app_category: str | None = None  # Regular Apps category, None for settings


class MainState(Immutable):
    """Main Redux state for the UI navigation and view."""

    # Full navigation stack as source of truth
    stack: tuple[StackItemType, ...] = ()
    # Derived from stack by reducer - menu keys representing navigation path
    path: tuple[str, ...] = ()
    is_header_visible: bool = True
    is_footer_visible: bool = True
    apps_items_priorities: dict[str, int] = field(default_factory=dict)
    settings_items_priorities: dict[str, int] = field(default_factory=dict)
    # Serializable registry of all registered apps and settings
    registered_apps: dict[str, RegisteredAppEntry] = field(default_factory=dict)
    is_recording: bool = False
    is_replaying: bool = False
    recorded_sequence: tuple[KeypadAction, ...] = ()
    # New: Computed view data for dumb UI architecture
    current_view: ViewData | None = None
    status_bar: StatusBarData | None = None
    # True while the GUI client has a transient local-only overlay open (e.g.
    # the notification extra-information page), which lives only on the GUI's
    # Kivy stack and not on this stack. BACK must close that overlay instead of
    # popping the core stack — see the MenuGoBackAction reducer branch.
    is_local_overlay_open: bool = False
