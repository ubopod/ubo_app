# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ubo_handle import Service, register

    from ubo_app.utils.types import Subscriptions


async def setup(service: Service) -> Subscriptions:
    from reducer import reducer
    from setup import init_service

    service.register_reducer(reducer)

    return await init_service()


register(
    service_id='users',
    label='Users',
    setup=setup,
)
