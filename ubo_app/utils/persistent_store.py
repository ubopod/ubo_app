"""Utility functions to work with the persistent storage."""

from __future__ import annotations

import json
import json.decoder
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar, cast, overload

import fasteners

from ubo_app.constants import PERSISTENT_STORE_PATH

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.store.main import RootState

T = TypeVar('T')

persistent_store_lock = fasteners.ReaderWriterLock()


def register_persistent_store(
    key: str,
    selector: Callable[[RootState], T],
) -> None:
    """Register a part of the store to be persistent in the file system."""
    from ubo_app.store.main import store

    @store.autorun(selector)
    async def _(value: T) -> None:
        if value is None:
            return
        with persistent_store_lock.write_lock():
            try:
                current_state = json.loads(Path(PERSISTENT_STORE_PATH).read_text())
            except (FileNotFoundError, json.decoder.JSONDecodeError):
                current_state = {}
            serialized_value = store.serialize_value(value)
            current_state[key] = serialized_value
            Path(PERSISTENT_STORE_PATH).write_text(json.dumps(current_state, indent=2))


@overload
def read_from_persistent_store(key: str) -> str: ...
@overload
def read_from_persistent_store(
    key: str,
    *,
    mapper: Callable[[str], T],
) -> T: ...
@overload
def read_from_persistent_store(
    key: str,
    *,
    output_type: type[T],
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
    mapper: Callable[[str], T],
) -> T: ...
@overload
def read_from_persistent_store(
    key: str,
    *,
    default: T,
    output_type: type[T],
) -> T: ...


def read_from_persistent_store(
    key: str,
    *,
    default: T | None = None,
    output_type: type[T] | None = None,
    mapper: Callable[[str], T] | None = None,
) -> T | None:
    """Read a part of the store from the file system."""
    from ubo_app.store.main import store

    if output_type is not None and mapper:
        msg = 'You cannot specify both `output_type` and `mapper` arguments.'
        raise ValueError(msg)

    try:
        with persistent_store_lock.read_lock():
            file_content = Path(PERSISTENT_STORE_PATH).read_text()
        current_state = json.loads(file_content)
    except (FileNotFoundError, json.decoder.JSONDecodeError):
        current_state = {}
    value = current_state.get(key)
    if value is None:
        return (
            (None if output_type is None else output_type())
            if default is None
            else default
        )

    if mapper:
        return mapper(value)
    return store.load_object(
        value,
        object_type=cast('type[T]', output_type),
    )
