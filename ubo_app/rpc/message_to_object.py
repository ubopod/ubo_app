# ruff: noqa: SLF001, S101, D100, D103
from __future__ import annotations

import enum
import importlib
from datetime import UTC, datetime
from typing import TypeAlias, TypeVar, cast, overload

import betterproto
import betterproto.casing
from betterproto import Enum
from immutable import Immutable

ReturnType: TypeAlias = (
    Immutable
    | enum.Enum
    | int
    | float
    | str
    | bool
    | None
    | datetime
    | list['ReturnType']
)

META_FIELD_PREFIX_PACKAGE_NAME = 'meta_field_package_name_'


def get_class(message: betterproto.Message) -> type | None:
    source_class = type(message)
    class_name = source_class.__name__

    first_field_name = source_class._betterproto.field_name_by_number[1]
    if first_field_name.startswith(META_FIELD_PREFIX_PACKAGE_NAME):
        package_name = first_field_name[len(META_FIELD_PREFIX_PACKAGE_NAME) :]
    else:
        return None

    destination_module_path = f'ubo_app.store.services.{package_name}'
    destination_module = importlib.import_module(destination_module_path)

    return getattr(destination_module, class_name, None)


def reduce_group(message: betterproto.Message) -> betterproto.Message:
    assert len(message._group_current) == 1
    attribute = next(iter(message._group_current.values()))

    return getattr(message, attribute)


T = TypeVar('T', bound=Immutable)


@overload
def rebuild_object(
    message: betterproto.Message | list[betterproto.Message],
    expected_type: type[T],
) -> T: ...
@overload
def rebuild_object(
    message: betterproto.Message | list[betterproto.Message],
) -> ReturnType: ...
def rebuild_object(  # noqa: C901
    message: betterproto.Message | list[betterproto.Message],
    expected_type: type[T] | None = None,
) -> ReturnType | T:
    if isinstance(message, int | float | str | bool | None):
        return cast(ReturnType, message)

    if isinstance(message, list):
        return [rebuild_object(item) for item in message]

    if hasattr(message, '_group_current') and len(message._group_current) > 0:
        return rebuild_object(reduce_group(message))

    keys = message._betterproto_meta.sorted_field_names
    if len(keys) == 1 and keys[0] == 'items':
        return [rebuild_object(item) for item in getattr(message, 'items', [])]

    destination_class = get_class(message)
    if expected_type and (
        destination_class is None or not issubclass(destination_class, expected_type)
    ):
        msg = f'Expected {expected_type}, got {destination_class}'
        raise ValueError(msg)

    fields = {
        betterproto.casing.snake_case(key): datetime.fromtimestamp(
            getattr(message, key),
            tz=UTC,
        )
        if key.endswith('_timestamp')
        else rebuild_object(getattr(message, key))
        for key in keys
        if not key.startswith('meta_field_') and getattr(message, key) is not None
    }

    if len(fields) == 1 and 'list' in fields:
        return fields['list']

    if destination_class is None:
        msg = f'Class not found for {message}'
        raise ValueError(msg)

    if isinstance(message, Enum) and message.name:
        if message.name == 'UNSPECIFIED':
            return None
        return getattr(destination_class, message.name)

    if isinstance(destination_class, type) and issubclass(destination_class, Immutable):
        return destination_class(**fields)

    msg = f'Parsing {message} is not implemented yet'
    raise NotImplementedError(msg)
