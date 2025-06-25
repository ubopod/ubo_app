# ruff: noqa: D100, D103
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ubo_handle import ReducerRegistrar, register


def setup(register_reducer: ReducerRegistrar) -> None:
    from reducer import reducer

    register_reducer(reducer)

    from setup import init_service

    init_service()


register(
    service_id='keypad',
    label='Keypad',
    setup=setup,
)
