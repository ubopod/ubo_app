"""Implement a menu item that dispatches an action or an event."""

from __future__ import annotations

import sys
from dataclasses import field
from typing import TYPE_CHECKING

from ubo_gui.menu.types import ActionItem

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.store.main import UboAction, UboEvent


def _default_action() -> Callable[[], None]:
    # WARNING: Dirty hack ahead
    # This is to set the default value of `icon` based on the provided/default value of
    # `importance`
    from ubo_app.store.main import store

    parent_frame = sys._getframe().f_back  # noqa: SLF001
    if not parent_frame or not (operation := parent_frame.f_locals.get('operation')):
        msg = 'No operation provided for `DispatchItem`'
        raise ValueError(msg)
    return lambda: store.dispatch(operation)


class DispatchItem(ActionItem):
    """Menu item that dispatches an action or an event."""

    operation: UboAction | UboEvent
    action: Callable[[], None] = field(default_factory=_default_action)
