"""Implement a menu item that dispatches an action."""

from __future__ import annotations

from dataclasses import field
from typing import TYPE_CHECKING

from ubo_gui.menu.types import ActionItem

from ubo_app.utils.dataclass import default_provider

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.store.main import UboAction


def _default_action(store_action: UboAction) -> Callable[[], None]:
    def action() -> None:
        from ubo_app.store.main import store

        store.dispatch(store_action)

    setattr(action, '_is_default_action_of_ubo_dispatch_item', True)  # noqa: B010

    return action


class DispatchItem(ActionItem):
    """Menu item that dispatches an action."""

    store_action: UboAction
    action: Callable[[], None] = field(
        default_factory=default_provider(['store_action'], _default_action),
    )

    def __post_init__(self) -> None:
        """Post-initialization method."""
        if not getattr(self.action, '_is_default_action_of_ubo_dispatch_item', False):
            msg = 'The `action` attribute of `UboDispatchItem` must not be set'
            raise ValueError(msg)
