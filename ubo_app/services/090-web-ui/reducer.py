# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redux import BaseAction, ReducerResult


def reducer(
    state: None,
    action: BaseAction,
) -> ReducerResult[None, None, None]:
    _ = action
    return state
