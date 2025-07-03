# ruff: noqa: SLF001, S101, D100, D103
from __future__ import annotations

import enum
import importlib
from datetime import UTC, datetime
from typing import TypeAlias, TypeVar, Union, cast, get_args, get_origin

import betterproto
import betterproto.casing
from betterproto.lib.std.google import protobuf as betterproto_protobuf
from immutable import Immutable

ReturnType: TypeAlias = (
    Immutable
    | enum.Enum
    | int
    | float
    | str
    | bytes
    | bool
    | None
    | datetime
    | list['ReturnType']
    | set['ReturnType']
    | dict[str, 'ReturnType']
)


class _MissingType: ...


MISSING = _MissingType()
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


def rebuild_object(  # noqa: C901
    message: betterproto.Message | list[betterproto.Message],
) -> ReturnType:
    if isinstance(message, int | float | str | bytes | bool | None) and not isinstance(
        message,
        betterproto.Enum,
    ):
        return cast('ReturnType', message)

    if isinstance(
        message,
        betterproto_protobuf.DoubleValue
        | betterproto_protobuf.FloatValue
        | betterproto_protobuf.Int64Value
        | betterproto_protobuf.UInt64Value
        | betterproto_protobuf.Int32Value
        | betterproto_protobuf.UInt32Value
        | betterproto_protobuf.BoolValue
        | betterproto_protobuf.StringValue
        | betterproto_protobuf.BytesValue,
    ):
        return message.value

    if isinstance(message, betterproto_protobuf.Empty):
        return None

    if isinstance(message, list):
        return [rebuild_object(item) for item in message]

    if isinstance(message, dict):
        return {
            key: rebuild_object(value)
            for key, value in message.items()
            if value is not None
        }

    if hasattr(message, '_group_current') and len(message._group_current) > 0:
        return rebuild_object(reduce_group(message))

    destination_class = get_class(message)

    if isinstance(message, betterproto.Enum) and message.name:
        if message.name.endswith('UNSPECIFIED'):
            return None
        return getattr(destination_class, message.name)

    keys = message._betterproto.sorted_field_names
    if len(keys) == 1 and keys[0] == 'items':
        items = [rebuild_object(item) for item in getattr(message, 'items', [])]
        if type(message).__name__.endswith('SetType'):
            return set(items)
        return items

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
        betterproto.casing.snake_case(key): get_field_value(
            destination_class,
            message,
            key,
        )
        for key in keys
        if not key.startswith('meta_field_')
    }

    fields = {key: value for key, value in fields.items() if value is not MISSING}

    return destination_class(**fields)


def get_field_value(
    destination_class: type[Immutable],
    message: betterproto.Message,
    key: str,
) -> ReturnType | _MissingType:
    if getattr(message, key) is None:
        # check if destination_class which is a dataclass has a default value for this
        # field
        field_type = destination_class.__dataclass_fields__.get(key)
        origin = get_origin(field_type)
        is_none_accepted = (
            type(None) in get_args(field_type)
            if origin is Union
            else field_type is type(None)
        )

        if not is_none_accepted:
            return MISSING

        return None

    if key.endswith('_timestamp'):
        return datetime.fromtimestamp(
            getattr(message, key),
            tz=UTC,
        )

    return rebuild_object(getattr(message, key))
