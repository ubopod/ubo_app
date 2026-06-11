"""Shared types for Docker app entries."""

from __future__ import annotations

from dataclasses import field
from typing import TYPE_CHECKING

from immutable import Immutable

from ubo_app.constants import CONFIG_PATH

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

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
            | Awaitable[str]
            | Callable[[], str | Awaitable[str]],
        ]
        | None
    ) = None
    network_mode: str = 'bridge'
    dns: list[str] | None = None
    volumes: list[str] | None = None
    command: (
        str
        | list[str]
        | Callable[[], str | list[str] | Awaitable[str | list[str]]]
        | None
    ) = None
    category: str | None = None
    prepare: Callable[[], Awaitable[bool] | bool] | None = None
    # Called when the app/composition is removed, before its secret_keys are
    # cleared — for app-specific teardown beyond secrets (e.g. Hermes
    # deregistering its assistant LLM provider).
    cleanup: Callable[[], Awaitable[None] | None] | None = None
    is_composition: bool = False
    # When True, the app exposes a web UI/API with weak or no authentication,
    # so its published ports default to loopback (127.0.0.1) and a per-app menu
    # toggle lets the user opt into LAN (0.0.0.0) exposure. Apps that ship their
    # own login leave this False and keep their default 0.0.0.0 binding.
    supports_lan_toggle: bool = False
    secret_keys: tuple[str, ...] = ()
    menu_actions: (
        Callable[[str, list[MenuItemData], dict[str, list[str]]], None] | None
    ) = None

    @property
    def full_path(self) -> str:
        """Get full image path including registry if specified."""
        return f'{self.registry}/{self.path}'
