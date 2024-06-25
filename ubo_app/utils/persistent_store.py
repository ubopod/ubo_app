"""Utility functions to work with the persistent storage."""

from __future__ import annotations

import json
from asyncio import Lock
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar, cast, overload

from redux import FinishEvent

from ubo_app.constants import PERSISTENT_STORE_PATH

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.store.main import RootState

T = TypeVar('T')

persistent_store_lock = Lock()


def register_persistent_store(
    key: str,
    selector: Callable[[RootState], T],
) -> None:
    """Register a part of the store to be persistent in the filesystem."""
    from ubo_app.store.main import autorun, store, subscribe_event

    @autorun(selector)
    async def write(value: T) -> None:
        if value is None:
            return
        async with persistent_store_lock:
            try:
                current_state = json.loads(Path(PERSISTENT_STORE_PATH).read_text())
            except FileNotFoundError:
                current_state = {}
            serialized_value = store.serialize_value(value)
            current_state[key] = serialized_value
            Path(PERSISTENT_STORE_PATH).write_text(json.dumps(current_state, indent=2))

    subscribe_event(FinishEvent, write.unsubscribe)


@overload
def read_from_persistent_store(key: str) -> None: ...
@overload
def read_from_persistent_store(
    key: str,
    *,
    object_type: type[T],
) -> T: ...
@overload
def read_from_persistent_store(
    key: str,
    *,
    default: T,
) -> T: ...
@overload
def read_from_persistent_store(
    key: str,
    *,
    default: T,
    object_type: type[T],
) -> T: ...


def read_from_persistent_store(
    key: str,
    *,
    default: T | None = None,
    object_type: type[T] | None = None,
) -> T | None:
    """Read a part of the store from the filesystem."""
    from ubo_app.store.main import store

    for _ in range(5):
        try:
            file_content = Path(PERSISTENT_STORE_PATH).read_text()
            current_state = json.loads(file_content)
        except FileNotFoundError:
            return (
                (None if object_type is None else object_type())
                if default is None
                else default
            )
        except json.JSONDecodeError:
            continue
        else:
            break
    else:
        msg = 'Failed to read from the persistent store'
        raise RuntimeError(msg)
    value = current_state.get(key)
    if value is None:
        return (
            (None if object_type is None else object_type())
            if default is None
            else default
        )
    return store.load_object(
        value,
        object_type=cast(type[T], object_type),
    )
