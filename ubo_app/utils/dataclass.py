"""Utility functions for dataclasses."""

from __future__ import annotations

import dataclasses
import sys
from typing import TYPE_CHECKING

from typing_extensions import TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

T = TypeVar('T', infer_variance=True)
_NOT_PROVIDED = object()


_FactoryType: type | None = None


def _extract_factory_type() -> None:
    """Extract the type of the factory function."""
    parent_frame = sys._getframe().f_back  # noqa: SLF001
    if not parent_frame:
        msg = 'No parent frame found'
        raise RuntimeError(msg)
    factory_instance = parent_frame.f_locals['sample_factory_field']
    global _FactoryType  # noqa: PLW0603
    _FactoryType = type(factory_instance)


@dataclasses.dataclass
class _Sample:
    sample_factory_field: str = dataclasses.field(default_factory=lambda: 'some_value')
    watcher_field: None = dataclasses.field(default_factory=_extract_factory_type)


_Sample()


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
            if _FactoryType and isinstance(value, _FactoryType):
                value = None
            values.append(value)

        return provider(*values)

    return default_provider
