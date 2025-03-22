from collections.abc import Callable, Coroutine
from typing import Protocol, TypeAlias

from redux import ReducerType

from ubo_app.utils.types import Subscriptions

class ReducerRegistrar(Protocol):
    def __call__(self: ReducerRegistrar, reducer: ReducerType) -> None: ...

SetupFunctionReturnType: TypeAlias = (
    Coroutine[None, None, Subscriptions | None] | Subscriptions | None
)

SetupFunction: TypeAlias = (
    Callable[[ReducerRegistrar], SetupFunctionReturnType]
    | Callable[[], SetupFunctionReturnType]
)

def register(
    *,
    service_id: str,
    label: str,
    setup: SetupFunction,
) -> None: ...
