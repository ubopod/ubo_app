"""Constants for the core store module.

This module provides a single source of truth for hardcoded values used across
the UI Redux architecture.
"""

from __future__ import annotations

from ubo_app.store.core.types.enums import SettingsCategory

# Number of menu items displayed per page
PAGE_SIZE = 3

# Nerd font icon characters used for stripping from titles
# These are common icon prefixes that appear before menu titles
NERD_FONT_ICON_CHARS = '󰀁󰀂󰀃󰀄󰀅󰀆󰀇󰀈󰀉󰀊󰀋󰀌󰀍󰀎󰀏󰀐󰀑󰀒󰀓󰀔󰀕󰀖󰀗󰀘󰀙󰀚󰀛󰀜󰀝󰀞󰀟󰡉󱛃󰖩󰨞'

# Settings category icons mapping (Nerd Font icons)
SETTINGS_CATEGORY_ICONS: dict[SettingsCategory, str] = {
    SettingsCategory.NETWORK: '󰛳',
    SettingsCategory.REMOTE: '󰑔',
    SettingsCategory.SYSTEM: '󰒔',
    SettingsCategory.HARDWARE: '',
    SettingsCategory.ASSISTANT: '󰚩',
    SettingsCategory.DOCKER: '󰡨',
    SettingsCategory.ACCESSIBILITY: '󰙋',
}

# Note: Path-to-menu mappings and menu IDs are registered dynamically by
# the application via register_path_menu_matcher() in view_registry.py.
# This keeps the core generic and reusable across different applications.
