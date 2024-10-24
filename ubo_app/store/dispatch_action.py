"""Implement a menu item that dispatches an action."""

from __future__ import annotations

import sys
from dataclasses import field
from typing import TYPE_CHECKING

from ubo_gui.menu.types import ActionItem

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.store.main import UboAction


def _default_action() -> Callable[[], None]:
    # WARNING: Dirty hack ahead
    # This is to set the default value of `icon` based on the provided/default value of
    # `importance`
    from ubo_app.store.main import store

    parent_frame = sys._getframe().f_back  # noqa: SLF001
    if not parent_frame or not (
        store_action := parent_frame.f_locals.get('store_action')
    ):
        msg = 'No store_action provided for `DispatchItem`'
        raise ValueError(msg)
    return lambda: store.dispatch(store_action)


class DispatchItem(ActionItem):
    """Menu item that dispatches an action."""

    store_action: UboAction
    action: Callable[[], None] = field(default_factory=_default_action)
