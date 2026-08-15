"""Entry point for the Wyoming service."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ubo_handle import ReducerRegistrar, register

    from ubo_app.utils.types import Subscriptions


async def setup(register_reducer: ReducerRegistrar) -> Subscriptions:
    """Register the reducer and start the Wyoming service."""
    from reducer import reducer

    register_reducer(reducer)

    from setup import init_service

    return await init_service()


register(
    service_id='wyoming',
    label='Home Assistant',
    setup=setup,
)
