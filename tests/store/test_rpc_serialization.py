"""Focused unit tests for the core gRPC serialization boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import betterproto
import pytest
from betterproto.lib.std.google import protobuf as betterproto_protobuf
from immutable import Immutable
from ubo_bindings.ubo import v1

from ubo_app.rpc.message_to_object import (
    MISSING,
    get_field_value,
    rebuild_object,
    reduce_group,
)
from ubo_app.rpc.object_to_message import build_message
from ubo_app.store.core.types import (
    ApplicationViewData,
    MenuItemData,
    MenuViewData,
    OpenRenderAction,
)
from ubo_app.store.input.types import InputMethod, InputResult
from ubo_app.store.services.mcp import StdioMcpConfig

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.store.ubo_actions import BasicType


@dataclass(eq=False, repr=False)
class StringSetType(betterproto.Message):
    """Minimal generated-style wrapper used to exercise set reconstruction."""

    items: list[str] = betterproto.string_field(1)  # noqa: RUF009


@dataclass(eq=False, repr=False)
class _StampMessage(betterproto.Message):
    """Generated-style message carrying a numeric ``*_timestamp`` field."""

    created_timestamp: float = betterproto.double_field(1)


class _StampObject(Immutable):
    """Destination whose ``*_timestamp`` field is a resolved datetime."""

    created_timestamp: datetime


class _RequiredChildObject(Immutable):
    """Destination with a non-nullable message field (no ``None`` accepted)."""

    child: MenuItemData


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


def test_protobuf_scalar_wrappers_and_empty_unwrap() -> None:
    """Wrapper messages unwrap to their scalar; ``Empty`` becomes ``None``."""
    assert rebuild_object(betterproto_protobuf.StringValue(value='x')) == 'x'
    assert rebuild_object(betterproto_protobuf.Int64Value(value=7)) == 7
    assert rebuild_object(betterproto_protobuf.BoolValue(value=True)) is True
    assert rebuild_object(betterproto_protobuf.Empty()) is None


# The three tests below pin down deliberately permissive runtime behaviour whose
# signatures are narrower than what the functions actually accept (a bare enum
# rather than a Message, a non-Immutable ``expected_type``, an untyped list). The
# casts keep the type checker out of the way of exercising exactly that.


def test_unspecified_enum_member_rebuilds_as_none() -> None:
    """A generated enum in its ``*_UNSPECIFIED`` state maps back to ``None``."""
    assert rebuild_object(cast('betterproto.Message', v1.InputMethod(0))) is None


def test_build_message_enum_falls_back_to_value() -> None:
    """A StrEnum serializes to its value with no or a non-enum expected type."""
    assert build_message(InputMethod.WEB_DASHBOARD) == InputMethod.WEB_DASHBOARD.value
    assert (
        build_message(
            InputMethod.WEB_DASHBOARD,
            expected_type=cast('Any', str),
        )
        == InputMethod.WEB_DASHBOARD.value
    )


def test_build_message_list_without_expected_type_maps_items() -> None:
    """An untyped sequence serializes element-by-element to a plain list."""
    assert build_message(cast('Any', [1, 'two', True])) == [1, 'two', True]


def test_stdio_mcp_env_dict_roundtrips_as_simple_string_wrapper() -> None:
    """A ``dict[str, str]`` field uses the simple ``items`` wrapper on the wire."""
    config = StdioMcpConfig(command='run', args=['--x'], env={'KEY': 'val', 'A': 'b'})

    message = cast('betterproto.Message', build_message(config))

    # Wire shape: env is a dedicated wrapper message carrying the raw dict.
    assert type(message.env).__name__ == 'StdioMcpConfigEnvDict'  # type: ignore[attr-defined]
    assert message.env.items == {'KEY': 'val', 'A': 'b'}  # type: ignore[attr-defined]

    rebuilt = cast('StdioMcpConfig', rebuild_object(message))
    assert rebuilt == config


def test_timestamp_field_rebuilds_as_utc_datetime() -> None:
    """A numeric ``*_timestamp`` field is rebuilt as a UTC-aware datetime."""
    value = get_field_value(
        _StampObject,
        _StampMessage(created_timestamp=1_700_000_000.0),
        'created_timestamp',
    )

    assert value == datetime.fromtimestamp(1_700_000_000.0, tz=UTC)


def test_non_nullable_missing_field_is_dropped() -> None:
    """An unset wire field for a non-nullable destination yields ``MISSING``."""
    message = cast('betterproto.Message', SimpleNamespace(child=None))

    assert get_field_value(_RequiredChildObject, message, 'child') is MISSING


def test_build_message_rejects_incompatible_expected_type() -> None:
    """A value that fits no wrapper arm of the expected type fails clearly."""
    item = MenuItemData(key='k', label='l', icon='i')

    with pytest.raises(ValueError, match='Expected'):
        build_message(item, expected_type=v1.ApplicationViewData)


def test_rebuild_object_maps_a_list_of_messages() -> None:
    """A bare list is rebuilt element-by-element through the same boundary."""
    rebuilt = rebuild_object(
        [
            betterproto_protobuf.StringValue(value='a'),
            betterproto_protobuf.Int64Value(value=1),
        ],
    )

    assert rebuilt == ['a', 1]


def test_action_wraps_through_nested_oneof() -> None:
    """An action is wrapped recursively when the target nests the action oneof."""
    action = OpenRenderAction(kind='text', title='Details', props={})

    wrapped = build_message(action, expected_type=v1.UboDispatchItemStoreAction)

    # Outer wrapper selects its ``ubo_action`` arm, which in turn selects the
    # concrete action arm — the recursive oneof-wrapping path.
    assert betterproto.which_one_of(wrapped, 'store_action')[0] == 'ubo_action'
    assert betterproto.which_one_of(wrapped.ubo_action, 'action')[0] == (
        'open_render_action'
    )
