"""Some useful type definitions."""

from collections.abc import Callable
from typing import TypeAlias

Subscriptions: TypeAlias = list[Callable[[], None]]
