"""Signature of the `register_service` function."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Protocol, TypeAlias

if TYPE_CHECKING:
    from redux import ReducerType


class Service(Protocol):
    """Utilities to initialize a service."""

    def register_reducer(self: Service, reducer: ReducerType) -> None:
        """Register a reducer."""


SetupFunction: TypeAlias = (
    Callable[[Service], Coroutine | None] | Callable[[], Coroutine | None]
)


def register(
    *,
    service_id: str,
    label: str,
    setup: SetupFunction,
) -> None:
    """Register a service, meant to be called in `ubo_handle.py` file of services."""
    _ = service_id, label, setup
    msg = 'This function is not meant to be called out of the services'
    raise NotImplementedError(msg)
