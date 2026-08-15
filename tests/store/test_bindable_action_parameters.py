"""Tests for parameters on bindable actions.

Covers the encoding a stored binding uses to carry its parameter values, and
the registry surface around it. The encoding is the load-bearing part: it is
what let parameters be added without changing how bindings are stored, so the
back-compat cases here are the point of the file, not an afterthought.
"""

from __future__ import annotations

import pytest

from ubo_app.store.core.bindable_actions import (
    BindableActionContext,
    BindableParameter,
    clear_all_bindable_actions,
    decode_binding,
    encode_binding,
    register_bindable_action,
    resolve_binding,
)
from ubo_app.store.core.types import ExecuteMenuActionAction

_CTX = BindableActionContext(protocol='', scancode='', device_name='test')


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    clear_all_bindable_actions()


def test_action_without_parameters_encodes_to_its_bare_key() -> None:
    """The common case has to stay byte-identical to what it was before."""
    assert encode_binding('rgb:red', {}) == 'rgb:red'


def test_binding_stored_before_parameters_existed_still_decodes() -> None:
    """No persisted data needed migrating because of exactly this."""
    assert decode_binding('rgb:red') == ('rgb:red', {})


def test_parameters_round_trip() -> None:
    """Values come back out exactly as they went in."""
    key, parameters = decode_binding(
        encode_binding('kiosk:set-output', {'port': 'hdmi_a_2', 'target': 'dash:ha'}),
    )

    assert key == 'kiosk:set-output'
    assert parameters == {'port': 'hdmi_a_2', 'target': 'dash:ha'}


def test_encoding_is_stable_regardless_of_mapping_order() -> None:
    """Callers deduplicate and compare bindings by value, so this must hold."""
    assert encode_binding('a:b', {'x': '1', 'y': '2'}) == encode_binding(
        'a:b',
        {'y': '2', 'x': '1'},
    )


@pytest.mark.parametrize(
    'value',
    ['a b', 'a&b=c', 'a?b', 'ünïcode', '100%', ''],
)
def test_values_needing_escaping_survive_the_round_trip(value: str) -> None:
    """Parameter values are user-supplied text, not just opaque ids."""
    _key, parameters = decode_binding(encode_binding('a:b', {'v': value}))

    assert parameters == {'v': value}


def test_resolve_binding_returns_action_and_parameters() -> None:
    """A stored binding resolves to the registered action plus its values."""
    register_bindable_action(
        'kiosk:set-output',
        'Kiosk: Set Output',
        lambda ctx: ExecuteMenuActionAction(
            action_id=f'kiosk:set:{ctx.parameters["port"]}',
        ),
        parameters=(BindableParameter(name='port', label='Output'),),
    )

    resolved = resolve_binding('kiosk:set-output?port=hdmi_a_2')

    assert resolved is not None
    action, parameters = resolved
    assert action.key == 'kiosk:set-output'
    assert parameters == {'port': 'hdmi_a_2'}


def test_resolved_parameters_reach_the_factory() -> None:
    """The whole point: one registration serving many stored bindings."""
    register_bindable_action(
        'kiosk:set-output',
        'Kiosk: Set Output',
        lambda ctx: ExecuteMenuActionAction(
            action_id=f'kiosk:set:{ctx.parameters["port"]}:{ctx.parameters["target"]}',
        ),
        parameters=(
            BindableParameter(name='port', label='Output'),
            BindableParameter(name='target', label='Shows'),
        ),
    )

    resolved = resolve_binding('kiosk:set-output?port=hdmi_a_2&target=dash%3Aha')
    assert resolved is not None
    action, parameters = resolved

    produced = action.factory(_CTX._replace(parameters=parameters))

    assert produced == ExecuteMenuActionAction(
        action_id='kiosk:set:hdmi_a_2:dash:ha',
    )


def test_resolve_binding_is_none_for_an_unregistered_key() -> None:
    """A binding whose owning service is gone, or whose target was deleted."""
    assert resolve_binding('kiosk:set-output?port=hdmi_a_2') is None


def test_existing_factories_see_an_empty_parameter_mapping() -> None:
    """Parameters ride on the context so no existing factory had to change."""
    assert _CTX.parameters == {}


def test_a_key_may_not_contain_the_parameter_separator() -> None:
    """It would decode as parameters, silently resolving to a truncated key."""
    with pytest.raises(ValueError, match='may not contain'):
        register_bindable_action(
            'kiosk:set?output',
            'Kiosk: Set Output',
            lambda _ctx: ExecuteMenuActionAction(action_id='kiosk:noop'),
        )
