# ruff: noqa: D100, D103
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ubo_handle import register


def setup() -> None:
    from setup import init_service

    init_service()


register(
    service_id='keyboard',
    label='Keyboard',
    setup=setup,
)
