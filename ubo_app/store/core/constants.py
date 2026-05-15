"""Constants for the core store module.

This module provides a single source of truth for hardcoded values used across
the UI Redux architecture.
"""

from __future__ import annotations

import math

from ubo_app.store.core.types.enums import SettingsCategory

# Number of menu items displayed per page
PAGE_SIZE = 3

# Number of visual slots consumed by heading + sub_heading in HeadedMenu
HEADED_MENU_HEADER_SLOTS = 2


def compute_total_pages(num_items: int, *, is_headed: bool = False) -> int:
    """Compute the number of pages needed to display menu items.

    For HeadedMenu, the heading and sub_heading occupy 2 visual slots on page 0,
    so the effective item count is increased accordingly.
    """
    effective = num_items + HEADED_MENU_HEADER_SLOTS if is_headed else num_items
    return max(1, math.ceil(effective / PAGE_SIZE))

# Nerd font icon characters used for stripping from titles
# These are common icon prefixes that appear before menu titles
NERD_FONT_ICON_CHARS = '󰀁󰀂󰀃󰀄󰀅󰀆󰀇󰀈󰀉󰀊󰀋󰀌󰀍󰀎󰀏󰀐󰀑󰀒󰀓󰀔󰀕󰀖󰀗󰀘󰀙󰀚󰀛󰀜󰀝󰀞󰀟󰡉󱛃󰖩󰨞'

# Settings category icons mapping (Nerd Font icons)
SETTINGS_CATEGORY_ICONS: dict[SettingsCategory, str] = {
    SettingsCategory.NETWORK: '󰛳',
    SettingsCategory.REMOTE: '󰑔',
    SettingsCategory.SYSTEM: '󰒔',
    SettingsCategory.HARDWARE: '',
    SettingsCategory.ASSISTANT: '󰚩',
    SettingsCategory.DOCKER: '󰡨',
    SettingsCategory.ACCESSIBILITY: '󰙋',
    SettingsCategory.LOCALIZATION: '󰵅',
}

# Action ID prefixes — single source of truth for stringly-typed prefixes
# used across Python and TypeScript (web-app/src/store/constants.ts).
NOTIFICATION_DISMISS_PREFIX = 'notification:dismiss:'
NOTIFICATION_EXTRA_INFO_PREFIX = 'notification:extra_info:'
NOTIFICATION_ACTION_PREFIX = 'notification:action:'
NOTIFICATION_CUSTOM_PREFIX = 'notification:custom:'
NOTIFICATION_DISPLAY_PREFIX = 'notification:display:'
MENU_SELECT_PREFIX = 'menu:select:'
MENU_NAVIGATE_PREFIX = 'menu:navigate:'
APPS_ROOT_CATEGORY = '__apps_root__'

# Note: Path-to-menu mappings and menu IDs are registered dynamically by
# the application via register_path_menu_matcher() in view_registry.py.
# This keeps the core generic and reusable across different applications.
