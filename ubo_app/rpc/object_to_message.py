# ruff: noqa: SLF001, D100, D103
from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Protocol, TypeAlias, TypeVar, cast, overload

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


def get_enum(object_: Enum) -> type[betterproto.Enum]:
    return getattr(
        ubo_bindings.ubo.v1,
        betterproto.casing.pascal_case(type(object_).__name__),
    )


T = TypeVar('T', bound=betterproto.Message)
DictWrapperT = TypeVar('DictWrapperT', bound='DictWrapperMessage')

GRPCSerializable: TypeAlias = 'Enum | Immutable | datetime | None'


class DictWrapperMessage(Protocol):
    """Protocol for betterproto messages that wrap a dict with an 'items' field."""

    def __init__(self, *, items: dict[str, str]) -> None:
        """Initialize with items dict."""


def _build_dict_wrapper_message(
    wrapper_cls: type[DictWrapperT],
    items: dict[str, str],
) -> DictWrapperT:
    """Build a dict wrapper message with proper typing."""
    return wrapper_cls(items=items)


def _try_wrap_oneof(
    object_: Immutable,
    message_class: type[betterproto.Message],
    expected_type: type[T],
) -> T | None:
    """Try to wrap object in a oneof wrapper if expected_type is a oneof wrapper.

    Returns the wrapped message if successful, None otherwise.
    """
    if not hasattr(expected_type, '_betterproto'):
        return None

    oneof_groups = expected_type._betterproto.oneof_group_by_field
    cls_by_field = expected_type._betterproto.cls_by_field

    # If all fields share the same oneof group, it's a oneof wrapper
    if not oneof_groups or len(set(oneof_groups.values())) != 1:
        return None

    # Find which field corresponds to message_class
    for field_name, field_cls in cls_by_field.items():
        if field_cls == message_class:
            # Build the inner message and wrap it
            inner_message = build_message(object_)
            return expected_type(**{field_name: inner_message})

    return None


@overload
def build_message(
    object_: GRPCSerializable,
    expected_type: type[T],
) -> T: ...
@overload
def build_message(
    object_: GRPCSerializable,
) -> ReturnType: ...
def build_message(  # noqa: C901, PLR0912
    object_: GRPCSerializable,
    expected_type: type[T] | None = None,
) -> ReturnType | T:
    if isinstance(object_, datetime):
        return object_.astimezone(UTC).timestamp()

    if (expected_type and issubclass(expected_type, betterproto.Enum)) or isinstance(
        object_,
        Enum,
    ):
        if not isinstance(object_, Enum):
            msg = f'Expected an Enum, got {type(object_)}'
            raise ValueError(msg)
        if expected_type is None:
            return object_.value
        if not issubclass(expected_type, betterproto.Enum):
            msg = f'Expected a betterproto.Enum, got {expected_type}'
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

    if isinstance(object_, dict):
        # Handle dict types - check if expected_type is a wrapper with 'items' field
        if expected_type and hasattr(expected_type, '_betterproto'):
            field_names = expected_type._betterproto.sorted_field_names
            if field_names == ('items',):
                # It's a dict wrapper like StdioMcpConfigEnvDict
                # Cast to DictWrapperMessage protocol for proper typing
                wrapper_cls = cast('type[DictWrapperMessage]', expected_type)
                return cast('T', _build_dict_wrapper_message(wrapper_cls, object_))
        # Otherwise return as-is (for map fields)
        return cast('ReturnType', object_)

    keys = object_.__dataclass_fields__.keys()

    message_class = get_class(object_)

    # Handle oneof wrapper types: if expected_type is a oneof wrapper and
    # message_class is one of the oneof variants, wrap it appropriately
    if expected_type and message_class and not issubclass(message_class, expected_type):
        wrapped = _try_wrap_oneof(object_, message_class, expected_type)
        if wrapped is not None:
            return wrapped
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
