"""Some useful type definitions."""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Sequence
from typing import TYPE_CHECKING, Protocol, TypeAlias

from typing_extensions import TypeVar

if TYPE_CHECKING:
    from asyncio import Handle

    from redux.basic_types import TaskCreatorCallback

Subscriptions: TypeAlias = Sequence[Callable[[], None | Coroutine[None, None, None]]]


TaskType = TypeVar('TaskType', infer_variance=True)


class CoroutineRunner(Protocol):
    """Run a coroutine in the event loop."""

    def __call__(
        self,
        coroutine: Coroutine[None, None, TaskType],
        callback: TaskCreatorCallback | None = None,
    ) -> Handle:
        """Run a coroutine in the event loop.

        Args:
            coroutine: The coroutine to run.
            callback: A callback to call when the coroutine is done.

        Returns:
            The handle of the task.

        """
        ...
