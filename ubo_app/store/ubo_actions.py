"""Implement a menu item that dispatches an action."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeAlias

from immutable import Immutable

if TYPE_CHECKING:
    from ubo_app.store.main import UboAction
    from ubo_app.utils.gui import UboPageWidget


class UboDispatchItem(Immutable):
    """Menu item that dispatches an action."""

    key: str | None = None
    label: str = ''
    icon: str | None = None
    color: str = '#ffffff'
    background_color: str | None = None
    is_short: bool = False
    store_action: UboAction | list[UboAction] | None = None


application_registry: dict[str, type[UboPageWidget]] = {}

BasicType: TypeAlias = str | bytes | int | float | bool | None


class UboApplicationItem(Immutable):
    """Immutable application item."""

    application_id: str
    key: str | None = None
    label: str = ''
    icon: str | None = None
    color: str = '#ffffff'
    background_color: str | None = None
    is_short: bool = False
    initialization_args: tuple[BasicType, ...] = ()
    initialization_kwargs: dict[str, BasicType] | None = None


def register_application(
    *,
    application_id: str,
    application: type[UboPageWidget],
) -> None:
    """Register an application in the application registry."""
    if application_id in application_registry:
        msg = f'Application ID {application_id} is already registered.'
        raise ValueError(msg)

    application_registry[application_id] = application


def get_registered_application(
    application_id: str,
) -> type[UboPageWidget]:
    """Get a registered application by its ID."""
    if application_id not in application_registry:
        msg = f'Application ID {application_id} is not registered.'
        raise ValueError(msg)

    return application_registry[application_id]
