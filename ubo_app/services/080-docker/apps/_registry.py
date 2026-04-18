"""Shared types for Docker app entries."""

from __future__ import annotations

from dataclasses import field
from typing import TYPE_CHECKING, Any

from immutable import Immutable

from ubo_app.constants import CONFIG_PATH

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from ubo_app.store.core.types import MenuItemData

COMPOSITIONS_PATH = CONFIG_PATH / 'docker_compositions'


class ContainerEntry(Immutable):
    """Container entry."""

    id: str
    label: str
    icon: str
    path: str
    registry: str
    dependencies: list[str] | None = None
    ports: dict[str, int | list[int] | tuple[str, int] | None] = field(
        default_factory=dict,
    )
    hosts: dict[str, str] = field(default_factory=dict)
    hostname: str | None = None
    note: str | None = None
    environment_vairables: (
        dict[
            str,
            str
            | Coroutine[Any, Any, str]
            | Callable[[], str | Coroutine[Any, Any, str]],
        ]
        | None
    ) = None
    network_mode: str = 'bridge'
    dns: list[str] | None = None
    volumes: list[str] | None = None
    command: (
        str
        | list[str]
        | Callable[[], str | list[str] | Coroutine[Any, Any, str | list[str]]]
        | None
    ) = None
    prepare: Callable[[], Coroutine[Any, Any, bool] | bool] | None = None
    is_composition: bool = False
    secret_keys: tuple[str, ...] = ()
    menu_actions: (
        Callable[[str, list[MenuItemData], dict[str, list[str]]], None] | None
    ) = None

    @property
    def full_path(self) -> str:
        """Get full image path including registry if specified."""
        return f'{self.registry}/{self.path}'
