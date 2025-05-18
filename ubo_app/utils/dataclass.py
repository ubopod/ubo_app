"""Utility functions for dataclasses."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from typing_extensions import TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

T = TypeVar('T', infer_variance=True)
_NOT_PROVIDED = object()


def default_provider(
    required_fields: Iterable[str],
    provider: Callable[..., T],
) -> Callable[[], T]:
    """Provide value for a dataclass field based on a combination of other fields."""
    # WARNING: Dirty hack ahead
    # This is to set the default value of a dataclass field based on the
    # provided/default value of a set of other dataclass fields

    def default_provider() -> T:
        parent_frame = sys._getframe().f_back  # noqa: SLF001
        values = []
        for field in required_fields:
            if (
                not parent_frame
                or (value := parent_frame.f_locals.get(field, _NOT_PROVIDED))
                is _NOT_PROVIDED
            ):
                msg = f'No {field} provided'
                raise ValueError(msg)
            values.append(value)

        return provider(*values)

    return default_provider
