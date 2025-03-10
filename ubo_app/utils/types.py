"""Some useful type definitions."""

from collections.abc import Callable, Coroutine, Sequence
from typing import TypeAlias

Subscriptions: TypeAlias = Sequence[Callable[[], None | Coroutine[None, None, None]]]
