"""Constants for the core store module.

This module provides a single source of truth for hardcoded values used across
the UI Redux architecture.
"""

from __future__ import annotations

# Number of menu items displayed per page
PAGE_SIZE = 3

# Nerd font icon characters used for stripping from titles
# These are common icon prefixes that appear before menu titles
NERD_FONT_ICON_CHARS = '󰀁󰀂󰀃󰀄󰀅󰀆󰀇󰀈󰀉󰀊󰀋󰀌󰀍󰀎󰀏󰀐󰀑󰀒󰀓󰀔󰀕󰀖󰀗󰀘󰀙󰀚󰀛󰀜󰀝󰀞󰀟󰡉󱛃󰖩󰨞'

# Direct path-to-menu mappings for known navigation paths
# Maps tuple of path segments to dynamic menu IDs
PATH_TO_MENU_ID_MAPPINGS: dict[tuple[str, ...], str] = {
    # Core menus
    ('main',): 'main:menu',
    ('main', 'apps'): 'apps:list',
    ('main', 'settings'): 'settings:categories',
    ('notifications',): 'notifications:list',
    ('power',): 'power:options',
}

# Settings -> Category -> Service mappings
# Maps (service_prefix, key_suffix) to dynamic menu IDs
SETTINGS_MENU_MAPPINGS: dict[tuple[str, str], str] = {
    # Display service
    ('000-display', ''): 'display:timeout',
    # Speech synthesis service
    ('010-speech-synthesis', 'engines'): 'speech-synthesis:main',
    ('010-speech-synthesis', 'settings'): 'speech-synthesis:picovoice',
    # Docker setup
    ('080-docker', 'service'): 'docker:setup',
    ('080-docker', 'registries'): 'docker:registries',
}

# Dynamic Menu IDs for core menus (also defined in menus.py for convenience)
NOTIFICATIONS_MENU_ID = 'notifications:list'
HOME_MENU_ID = 'home:main'
MAIN_MENU_ID = 'main:menu'
APPS_MENU_ID = 'apps:list'
SETTINGS_MENU_ID = 'settings:categories'
POWER_MENU_ID = 'power:options'
