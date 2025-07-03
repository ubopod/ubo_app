# ruff: noqa: SLF001, D100, D103
from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, TypeAlias, TypeVar, cast, overload

import betterproto
import betterproto.casing

import ubo_bindings.ubo.v1

if TYPE_CHECKING:
    from immutable import Immutable

ReturnType: TypeAlias = (
    betterproto.Message
    | betterproto.Enum
    | int
    | float
    | str
    | bytes
    | bool
    | None
    | list['ReturnType']
)


def get_class(object_: Immutable) -> type[betterproto.Message]:
    return getattr(
        ubo_bindings.ubo.v1,
        betterproto.casing.pascal_case(type(object_).__name__),
    )


T = TypeVar('T', bound=betterproto.Message)

GRPCSerializable: TypeAlias = 'Enum | Immutable | datetime | None'


@overload
def build_message(
    object_: GRPCSerializable,
    expected_type: type[T],
) -> T: ...
@overload
def build_message(
    object_: GRPCSerializable,
) -> ReturnType: ...
def build_message(  # noqa: C901
    object_: GRPCSerializable,
    expected_type: type[T] | None = None,
) -> ReturnType | T:
    if isinstance(object_, datetime):
        return object_.astimezone(UTC).timestamp()

    if (expected_type and issubclass(expected_type, betterproto.Enum)) or isinstance(
        object_,
        Enum,
    ):
        if expected_type is None or not issubclass(expected_type, betterproto.Enum):
            msg = f'Expected a betterproto.Enum, got {expected_type}'
            raise ValueError(msg)
        if not isinstance(object_, Enum):
            msg = f'Expected an Enum, got {type(object_)}'
            raise ValueError(msg)
        return getattr(
            expected_type,
            cast('str', 'UNSPECIFIED' if object_ is None else object_.name),
        )

    if isinstance(object_, int | float | str | bytes | bool | None):
        return cast('ReturnType', object_)

    if isinstance(object_, list | tuple):
        if expected_type:
            if hasattr(
                expected_type,
                '_betterproto',
            ) and expected_type._betterproto.sorted_field_names == ('items',):
                fields = {
                    'items': [
                        build_message(
                            item,
                            expected_type=expected_type._betterproto.cls_by_field[
                                'items'
                            ],
                        )
                        for item in object_
                    ],
                }
                return expected_type(**fields)
            return [
                build_message(item, expected_type=expected_type) for item in object_
            ]
        return [build_message(item) for item in object_]

    keys = object_.__dataclass_fields__.keys()

    message_class = get_class(object_)
    if expected_type and (
        message_class is None or not issubclass(message_class, expected_type)
    ):
        msg = f'Expected {expected_type}, got {message_class}'
        raise ValueError(msg)

    fields = {
        betterproto.casing.snake_case(key): build_message(
            getattr(object_, key),
            expected_type=message_class._betterproto.cls_by_field[key],
        )
        for key in keys
    }

    if message_class is None:
        msg = f'Class not found for {object_}'
        raise ValueError(msg)

    if issubclass(message_class, betterproto.Message):
        return message_class(**fields)

    msg = f'Building message from {object_} is not implemented yet'
    raise NotImplementedError(msg)
