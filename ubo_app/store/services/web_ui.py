# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from typing import TYPE_CHECKING

from immutable import Immutable

if TYPE_CHECKING:
    from ubo_app.store.operations import InputDescription


class WebUIState(Immutable):
    active_inputs: list[InputDescription]
