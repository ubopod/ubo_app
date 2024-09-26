# ruff: noqa: SLF001, S101, D100, D103
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, TypeAlias, TypeVar, cast, overload

import betterproto
import betterproto.casing

import ubo_app.rpc.generated.ubo.v1

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
        ubo_app.rpc.generated.ubo.v1,
        type(object_).__name__,
    )


T = TypeVar('T', bound=betterproto.Message)


@overload
def build_message(
    object_: Immutable | list[Immutable] | datetime | None,
    expected_type: type[T],
) -> T: ...
@overload
def build_message(
    object_: Immutable | list[Immutable] | datetime | None,
) -> ReturnType: ...
def build_message(
    object_: Immutable | list[Immutable] | datetime | None,
    expected_type: type[T] | None = None,
) -> ReturnType | T:
    if isinstance(object_, datetime):
        return object_.astimezone(UTC).timestamp()

    if expected_type and issubclass(expected_type, betterproto.Enum):
        return getattr(
            expected_type,
            cast(str, 'UNSPECIFIED' if object_ is None else str(object_)),
        )

    if isinstance(object_, int | float | str | bytes | bool | None):
        return cast(ReturnType, object_)

    if isinstance(object_, list | tuple):
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
