"""Camera settings menu pages.

Camera menu functionality has been migrated to dynamic menus.
The menu is now managed via ``UpdateDynamicMenuAction`` dispatched from
``setup.py:update_camera_dynamic_menu``.

Action handlers are registered with ``register_action`` for:
- ``camera:detect`` - triggers camera detection
- ``camera:select:<index>`` - selects a specific camera by index

The menu ID constant ``CAMERA_MENU_ID`` is defined in ``setup.py``.
"""

from __future__ import annotations

from setup import CAMERA_MENU_ID

__all__ = ['CAMERA_MENU_ID']
