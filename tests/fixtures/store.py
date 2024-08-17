"""Store tests fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from redux import Store


@pytest.fixture
def store() -> Store:
    """Take a snapshot of the store."""
    from ubo_app.store.main import store

    return store
