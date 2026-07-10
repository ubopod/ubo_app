"""Focused unit tests for the core gRPC serialization boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import betterproto
import pytest
from ubo_bindings.ubo import v1

from ubo_app.rpc.message_to_object import rebuild_object, reduce_group
from ubo_app.rpc.object_to_message import build_message
from ubo_app.store.core.types import (
    ApplicationViewData,
    MenuItemData,
    MenuViewData,
    OpenRenderAction,
)
from ubo_app.store.input.types import InputMethod, InputResult

if TYPE_CHECKING:
    from collections.abc import Callable

    from immutable import Immutable

    from ubo_app.store.ubo_actions import BasicType


@dataclass(eq=False, repr=False)
class StringSetType(betterproto.Message):
    """Minimal generated-style wrapper used to exercise set reconstruction."""

    items: list[str] = betterproto.string_field(1)  # noqa: RUF009


def _roundtrip(value: Immutable) -> object:
    """Serialize and rebuild one immutable value."""
    message = cast('betterproto.Message', build_message(value))
    return rebuild_object(message)


def test_extra_data_roundtrip_preserves_scalars_lists_and_none() -> None:
    """BasicType maps preserve every supported scalar and sequence shape."""
    extra_data = {
        'text': 'hello',
        'enabled': True,
        'count': 3,
        'ratio': 1.5,
        'payload': b'bytes',
        'missing': None,
        'values': ['one', 2, False, None],
    }
    value = ApplicationViewData(application_id='demo', extra_data=extra_data)

    rebuilt = cast('ApplicationViewData', _roundtrip(value))

    assert rebuilt.extra_data == extra_data


def test_optional_menu_items_roundtrip_preserves_empty_slots() -> None:
    """Tuple item wrappers preserve both messages and explicit None entries."""
    item = MenuItemData(key='first', label='First', icon='1')
    value = MenuViewData(title='Optional items', items=(item, None))

    rebuilt = cast('MenuViewData', _roundtrip(value))

    rebuilt_item = rebuilt.items[0]
    assert rebuilt_item is not None
    assert rebuilt_item.key == item.key
    assert rebuilt_item.label == item.label
    assert rebuilt_item.icon == item.icon
    assert rebuilt.items[1] is None


def test_enum_and_primitive_maps_roundtrip() -> None:
    """Enums and protobuf-native map values survive the same boundary."""
    value = InputResult(
        data={'answer': 'yes'},
        files={'payload.bin': b'payload'},
        method=InputMethod.WEB_DASHBOARD,
    )

    rebuilt = cast('InputResult', _roundtrip(value))

    assert rebuilt.data == value.data
    assert rebuilt.files == value.files
    assert rebuilt.method.value == InputMethod.WEB_DASHBOARD.value


def test_action_oneof_wrapper_roundtrip() -> None:
    """A concrete action can be wrapped in and rebuilt from the wire oneof."""
    action = OpenRenderAction(
        kind='text_viewer',
        title='Details',
        props={'text': 'hello', 'line_numbers': [1, 2]},
    )

    wrapped = build_message(action, expected_type=v1.Action)
    field_name, _ = betterproto.which_one_of(wrapped, 'action')
    rebuilt = cast('OpenRenderAction', rebuild_object(reduce_group(wrapped)))

    assert field_name == 'open_render_action'
    assert rebuilt.kind == action.kind
    assert rebuilt.title == action.title
    assert rebuilt.props == action.props


def test_set_wrapper_rebuilds_as_set() -> None:
    """Generated SetType wrappers are reconstructed with set semantics."""
    rebuilt = rebuild_object(StringSetType(items=['alpha', 'beta', 'alpha']))

    assert rebuilt == {'alpha', 'beta'}


def test_expected_enum_rejects_primitive_value() -> None:
    """Supplying a primitive for a generated enum fails at the boundary."""
    unchecked_build_message = cast('Callable[..., object]', build_message)
    with pytest.raises(ValueError, match='Expected an Enum'):
        unchecked_build_message('web_dashboard', expected_type=v1.InputMethod)


def test_extra_data_rejects_unsupported_nested_value() -> None:
    """Unsupported values inside BasicType maps fail clearly."""
    unsupported = cast('BasicType', object())
    value = ApplicationViewData(extra_data={'unsupported': unsupported})

    with pytest.raises(TypeError, match='Cannot convert'):
        build_message(value)
