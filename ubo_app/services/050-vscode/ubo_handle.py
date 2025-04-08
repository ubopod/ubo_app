# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ubo_handle import ReducerRegistrar, register

    from ubo_app.utils.types import Subscriptions


async def setup(register_reducer: ReducerRegistrar) -> Subscriptions:
    from reducer import reducer

    register_reducer(reducer)

    from setup import init_service

    return await init_service()


register(
    service_id='vscode',
    label='VSCode',
    setup=setup,
)
