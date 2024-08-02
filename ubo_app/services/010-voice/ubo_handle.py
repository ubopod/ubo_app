# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ubo_handle import Service, register


def setup(service: Service) -> None:
    from reducer import reducer
    from setup import init_service

    service.register_reducer(reducer)
    init_service()


register(
    service_id='voice',
    label='Voice',
    setup=setup,
)
