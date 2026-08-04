"""Tests for the shared MQTT contribution registry.

This registry is how services declare Home Assistant entities without importing
the bridge — it is a process-wide singleton, so registration hygiene (ordering,
re-registration, cleanup) is the contract.
"""

from __future__ import annotations

import importlib

import pytest

from ubo_app.store.services.mqtt import (
    MqttComponent,
    MqttRequestAnnounceAction,
)
from ubo_app.utils.mqtt_registry import (
    clear_all_mqtt_components,
    get_mqtt_components,
    register_mqtt_components,
    unregister_mqtt_components,
)


def _component(component_id: str) -> MqttComponent:
    return MqttComponent(
        component_id=component_id,
        platform='sensor',
        name=component_id,
    )


@pytest.fixture(autouse=True)
def _clean_registry() -> object:
    clear_all_mqtt_components()
    yield
    clear_all_mqtt_components()


def test_registration_order_is_preserved() -> None:
    """A stable order keeps the generated discovery payload deterministic."""
    register_mqtt_components('sensors', lambda: [_component('a')])
    register_mqtt_components('keypad', lambda: [_component('b')])

    assert [component.component_id for component in get_mqtt_components()] == ['a', 'b']


def test_the_provider_is_called_on_every_collection() -> None:
    """Contributions are live — a re-scan changes what sensors would return."""
    entities = [_component('a')]
    register_mqtt_components('sensors', lambda: entities)

    assert len(get_mqtt_components()) == 1

    entities.append(_component('b'))
    assert len(get_mqtt_components()) == 2


def test_duplicate_source_is_rejected_by_default() -> None:
    """Two services silently sharing a source id would lose one's entities."""
    register_mqtt_components('sensors', list)

    with pytest.raises(ValueError, match='already registered'):
        register_mqtt_components('sensors', list)



def test_the_returned_callable_unregisters() -> None:
    """`init_service` puts this straight into its subscriptions list."""
    unregister = register_mqtt_components('sensors', lambda: [_component('a')])
    assert get_mqtt_components()

    unregister()
    assert get_mqtt_components() == []


def test_unregistering_an_unknown_source_is_false_not_an_error() -> None:
    """Teardown runs on paths where registration may never have happened."""
    assert unregister_mqtt_components('nope') is False


def test_a_failing_provider_does_not_stop_the_others() -> None:
    """One misbehaving service must not stop the pod being announced."""

    def _broken() -> list[MqttComponent]:
        msg = 'provider exploded'
        raise RuntimeError(msg)

    register_mqtt_components('broken', _broken)
    register_mqtt_components('sensors', lambda: [_component('a')])

    assert [c.component_id for c in get_mqtt_components()] == ['a']


def test_registering_and_unregistering_asks_for_an_announce(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bridge has no other way to notice the contributor set changed.

    Without this, stopping a service leaves its entities on the Home Assistant
    dashboard until something unrelated happens to trigger an announce — and
    starting one leaves its entities missing.
    """
    # Patched on the store itself: `_request_announce` imports it at call time,
    # so there is no module attribute to stand in for it.
    store = importlib.import_module('ubo_app.store.main').store

    announces: list[object] = []
    monkeypatch.setattr(store, 'dispatch', lambda action: announces.append(action))

    register_mqtt_components('sensors', lambda: [_component('a')])
    assert len(announces) == 1

    unregister_mqtt_components('sensors')
    assert len(announces) == 2

    assert all(
        isinstance(action, MqttRequestAnnounceAction) for action in announces
    )
