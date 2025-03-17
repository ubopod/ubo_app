# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ubo_handle import ReducerRegistrar, register


async def setup(register_reducer: ReducerRegistrar) -> None:
    from reducer import reducer
    from setup import init_service

    register_reducer(reducer)
    init_service()


register(
    service_id='rpi_connect',
    label='RPi Connect',
    setup=setup,
)
