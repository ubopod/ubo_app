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

# Note: Path-to-menu mappings and menu IDs are registered dynamically by
# the application via register_path_menu_matcher() in view_registry.py.
# This keeps the core generic and reusable across different applications.
