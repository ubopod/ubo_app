from collections.abc import Callable, Coroutine
from typing import Protocol, TypeAlias

from redux import ReducerType

class Service(Protocol):
    def register_reducer(self: Service, reducer: ReducerType) -> None: ...

SetupFunction: TypeAlias = (
    Callable[[Service], Coroutine | None] | Callable[[], Coroutine | None]
)

def register(
    *,
    service_id: str,
    label: str,
    setup: SetupFunction,
) -> None: ...
