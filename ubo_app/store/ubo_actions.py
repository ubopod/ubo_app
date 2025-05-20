"""Implement a menu item that dispatches an action."""

from __future__ import annotations

from dataclasses import field
from typing import TYPE_CHECKING

from ubo_gui.menu.types import ActionItem, ApplicationItem

from ubo_app.utils.dataclass import default_provider

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_gui.page import PageWidget

    from ubo_app.store.main import UboAction


def _default_action(store_action: UboAction) -> Callable[[], None]:
    def action() -> None:
        from ubo_app.store.main import store

        store.dispatch(store_action)

    setattr(action, '_is_default_action_of_ubo_dispatch_item', True)  # noqa: B010

    return action


class UboDispatchItem(ActionItem):
    """Menu item that dispatches an action."""

    store_action: UboAction
    action: Callable[[], None] = field(
        default_factory=default_provider(['store_action'], _default_action),
    )

    def __post_init__(self: UboDispatchItem) -> None:
        """Post-initialization method."""
        if not getattr(self.action, '_is_default_action_of_ubo_dispatch_item', False):
            msg = 'The `action` attribute of `UboDispatchItem` must not be set'
            raise ValueError(msg)


application_registry: dict[str, type[PageWidget]] = {}


class UboApplicationItem(ApplicationItem):
    """Immutable application item."""

    # TODO(@sassanh): This is a hack to maintain backward compatibility  # noqa: FIX002
    # until #261 is implemented
    application: (
        PageWidget
        | Callable[[], PageWidget]
        | type[PageWidget]
        | Callable[[], type[PageWidget]]
    ) = field(
        default_factory=default_provider(
            ['application_id', 'initialization_args', 'initialization_kwargs'],
            lambda application_id,
            initialization_args,
            initialization_kwargs: lambda: application_registry[application_id](
                *(initialization_args),
                **(initialization_kwargs or {}),
            ),
        ),
    )

    application_id: str
    initialization_args: tuple = ()
    initialization_kwargs: dict | None = None


def register_application(
    *,
    application_id: str,
    application: type[PageWidget],
) -> None:
    """Register an application in the application registry."""
    if application_id in application_registry:
        msg = f'Application ID {application_id} is already registered.'
        raise ValueError(msg)

    application_registry[application_id] = application


def get_registered_application(
    application_id: str,
) -> type[PageWidget]:
    """Get a registered application by its ID."""
    if application_id not in application_registry:
        msg = f'Application ID {application_id} is not registered.'
        raise ValueError(msg)

    return application_registry[application_id]
