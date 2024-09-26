# ruff: noqa: SLF001, S101, D100, D103
from __future__ import annotations

import enum
import importlib
from datetime import UTC, datetime
from typing import TypeAlias, TypeVar, cast

import betterproto
import betterproto.casing
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
META_FIELD_PREFIX_PACKAGE_NAME_INDEX = 1000


def get_class(message: betterproto.Message | betterproto.Enum) -> type | None:
    class_name = type(message).__name__
    if isinstance(message, betterproto.Enum):
        unspecified_member = next(iter(type(message).__members__.keys()))
        destination_module_path = (
            unspecified_member[: -len('_UNSPECIFIED')].lower().replace('_dot_', '.')
        )
    elif (
        META_FIELD_PREFIX_PACKAGE_NAME_INDEX
        in type(message)._betterproto.field_name_by_number
    ):
        field_name = type(message)._betterproto.field_name_by_number[
            META_FIELD_PREFIX_PACKAGE_NAME_INDEX
        ]
        if field_name.startswith(META_FIELD_PREFIX_PACKAGE_NAME):
            destination_module_path = field_name[
                len(META_FIELD_PREFIX_PACKAGE_NAME) :
            ].replace('_dot_', '.')
        else:
            return None
    else:
        return None

    destination_module = importlib.import_module(destination_module_path)

    return getattr(destination_module, class_name, None)


def reduce_group(message: betterproto.Message) -> betterproto.Message:
    assert len(message._group_current) == 1
    attribute = next(iter(message._group_current.values()))

    return getattr(message, attribute)


T = TypeVar('T', bound=betterproto.Message | betterproto.Enum)


def rebuild_object(
    message: betterproto.Message | list[betterproto.Message],
) -> ReturnType:
    if isinstance(message, int | float | str | bytes | bool | None) and not isinstance(
        message,
        betterproto.Enum,
    ):
        return cast(ReturnType, message)

    if isinstance(message, list):
        return [rebuild_object(item) for item in message]

    if hasattr(message, '_group_current') and len(message._group_current) > 0:
        return rebuild_object(reduce_group(message))

    destination_class = get_class(message)

    if isinstance(message, betterproto.Enum) and message.name:
        if message.name.endswith('UNSPECIFIED'):
            return None
        return getattr(destination_class, message.name)

    keys = message._betterproto.sorted_field_names
    if len(keys) == 1 and keys[0] == 'items':
        return [rebuild_object(item) for item in getattr(message, 'items', [])]

    if destination_class is None:
        msg = f'Class not found for {message}'
        raise ValueError(msg)

    if not isinstance(destination_class, type) or not issubclass(
        destination_class,
        Immutable,
    ):
        msg = f'Parsing {message} is not implemented yet'
        raise NotImplementedError(msg)

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

    return destination_class(**fields)
