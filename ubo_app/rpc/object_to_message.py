# ruff: noqa: SLF001, D100, D103
from __future__ import annotations

import functools
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

# --- Caching for hot-path operations ---
_msg_class_cache: dict[type, type[betterproto.Message]] = {}
_enum_class_cache: dict[type, type[betterproto.Enum]] = {}
_pascal_case = functools.lru_cache(maxsize=512)(betterproto.casing.pascal_case)
_snake_case = functools.lru_cache(maxsize=512)(betterproto.casing.snake_case)


def get_class(object_: Immutable) -> type[betterproto.Message]:
    obj_type = type(object_)
    cached = _msg_class_cache.get(obj_type)
    if cached is not None:
        return cached
    result = getattr(ubo_bindings.ubo.v1, _pascal_case(obj_type.__name__))
    _msg_class_cache[obj_type] = result
    return result


def get_enum(object_: Enum) -> type[betterproto.Enum]:
    obj_type = type(object_)
    cached = _enum_class_cache.get(obj_type)
    if cached is not None:
        return cached
    result = getattr(ubo_bindings.ubo.v1, _pascal_case(obj_type.__name__))
    _enum_class_cache[obj_type] = result
    return result


T = TypeVar('T', bound=betterproto.Message)
DictWrapperT = TypeVar('DictWrapperT', bound='DictWrapperMessage')

GRPCSerializable: TypeAlias = 'Enum | Immutable | None'


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


def _convert_basic_value(
    value: object,
    value_cls: type[betterproto.Message],
) -> betterproto.Message:
    """Convert a Python value to a proto map-value message.

    Handles the ``BasicType`` wrapping used by ``extra_data`` maps:
    ``value_cls(basic_type=BasicType(field=value))``
    for scalar values, and the ``list`` oneof arm for sequences.
    """
    from ubo_bindings.ubo import v1

    if isinstance(value, str | int | float | bool | bytes | None):
        if value is None:
            basic_type = v1.BasicType()
        elif isinstance(value, str):
            basic_type = v1.BasicType(string=value)
        elif isinstance(value, bool):
            # bool before int since bool is subclass of int
            basic_type = v1.BasicType(bool=value)
        elif isinstance(value, int):
            basic_type = v1.BasicType(int64=value)
        elif isinstance(value, float):
            basic_type = v1.BasicType(float=value)
        else:
            basic_type = v1.BasicType(bytes=value)

        return value_cls(basic_type=basic_type)  # type: ignore[call-arg]

    if isinstance(value, list | tuple):
        # For list/tuple values, check if value_cls has a 'list' oneof arm
        list_cls = value_cls._betterproto.cls_by_field.get('list')
        if list_cls is not None:
            converted_items = [
                _convert_basic_value(item, value_cls) for item in value
            ]
            return value_cls(list=list_cls(items=converted_items))  # type: ignore[call-arg]

    msg = f'Cannot convert {type(value)} to {value_cls}'
    raise TypeError(msg)


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


def _try_wrap_single_field(
    object_: Immutable | None,
    message_class: type[betterproto.Message] | None,
    expected_type: type[T],
) -> T | None:
    """Try to wrap object in a single-field wrapper message.

    This handles the proto pattern for tuple[T | None, ...] where each item
    is wrapped in an ItemsItem message with a single optional field.

    Returns the wrapped message if successful, None otherwise.
    """
    if not hasattr(expected_type, '_betterproto'):
        return None

    # Check if expected_type has exactly one non-meta field
    field_names = [
        f for f in expected_type._betterproto.sorted_field_names
        if not f.startswith('meta_field_')
    ]

    if len(field_names) != 1:
        return None

    field_name = field_names[0]
    cls_by_field = expected_type._betterproto.cls_by_field

    # Check if the single field can hold message_class
    if field_name in cls_by_field:
        field_cls = cls_by_field[field_name]
        if message_class is None or field_cls == message_class:
            # Build the inner message (or None) and wrap it
            inner_message = None if object_ is None else build_message(object_)
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
    if (expected_type and issubclass(expected_type, betterproto.Enum)) or isinstance(
        object_,
        Enum,
    ):
        if not isinstance(object_, Enum):
            msg = f'Expected an Enum, got {type(object_)}'
            raise ValueError(msg)
        if expected_type is None:
            return object_.value
        # If expected_type is a primitive (e.g., str), return the enum's value
        # This handles StrEnum -> string proto field case
        if not issubclass(expected_type, betterproto.Enum):
            return object_.value
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
                cls_by_field = expected_type._betterproto.cls_by_field
                value_cls = cls_by_field.get('items.value')
                if value_cls is not None and issubclass(
                    value_cls, betterproto.Message,
                ):
                    # Map values need conversion (e.g. extra_data map)
                    converted = {
                        k: _convert_basic_value(v, value_cls)
                        for k, v in object_.items()
                    }
                    return cast('T', expected_type(items=converted))  # type: ignore[call-arg]
                # Simple dict wrapper (e.g. StdioMcpConfigEnvDict with str values)
                wrapper_cls = cast('type[DictWrapperMessage]', expected_type)
                return cast('T', _build_dict_wrapper_message(wrapper_cls, object_))
        # Otherwise return as-is (for map fields)
        return cast('ReturnType', object_)

    keys = object_.__dataclass_fields__.keys()

    message_class = get_class(object_)

    # Handle wrapper types: if expected_type is a wrapper and message_class
    # is the wrapped type, wrap it appropriately
    is_subclass = (
        message_class is not None
        and expected_type is not None
        and issubclass(message_class, expected_type)
    )
    if expected_type and not is_subclass:
        # Try oneof wrapper first
        if message_class:
            wrapped = _try_wrap_oneof(object_, message_class, expected_type)
            if wrapped is not None:
                return wrapped

        # Try single-field wrapper (for tuple[T | None, ...] pattern)
        wrapped = _try_wrap_single_field(object_, message_class, expected_type)
        if wrapped is not None:
            return wrapped

        if message_class:
            msg = f'Expected {expected_type}, got {message_class}'
            raise ValueError(msg)

    fields = {
        _snake_case(key): build_message(
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
