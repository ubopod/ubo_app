"""Tests for the MQTT bridge reducer.

The two transparent arms (`MqttPublishAction`, `MqttRequestAnnounceAction`) are
the whole reason other services can reach the bridge at all — services cannot
import each other, so they dispatch and the bridge subscribes. Those arms must
leave state untouched, or a 1 Hz sensor reading would churn the store.

The store types are imported normally: `load_service_modules` leaves `ubo_app.*`
alone, so the reducer's match-case and the test's constructed actions reference
the same class objects however the files are ordered.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from redux import CompleteReducerResult, InitAction, InitializationActionError

from tests.service_loader import load_service_modules
from ubo_app.store.services import mqtt as types

if TYPE_CHECKING:
    from ubo_app.store.services.mqtt import MqttState

(reducer_module,) = load_service_modules(
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '050-mqtt',
    'reducer',
)
reducer = reducer_module.reducer


def _state() -> MqttState:
    state = reducer(None, InitAction())
    assert isinstance(state, types.MqttState)
    return state


def test_none_state_without_init_raises() -> None:
    """Only `InitAction` may create the slice."""
    with pytest.raises(InitializationActionError):
        reducer(None, types.MqttSetEnabledAction(is_enabled=True))


def test_init_starts_disabled_and_closed() -> None:
    """Nothing is connected and remote control is opt-in."""
    state = _state()

    assert state.status is types.MqttConnectionStatus.DISABLED
    assert state.broker.source is types.MqttBrokerSource.BUNDLED
    assert state.broker.host == '127.0.0.1'
    assert state.broker.port == 1883
    assert state.allow_remote_control is False
    assert state.last_error is None


def test_status_records_the_error_only_while_erroring() -> None:
    """A stale error message next to a healthy connection is worse than none."""
    state = reducer(
        _state(),
        types.MqttSetStatusAction(
            status=types.MqttConnectionStatus.ERROR,
            error='connection refused',
        ),
    )
    assert state.last_error == 'connection refused'

    state = reducer(
        state,
        types.MqttSetStatusAction(status=types.MqttConnectionStatus.CONNECTED),
    )
    assert state.status is types.MqttConnectionStatus.CONNECTED
    assert state.last_error is None


def test_publish_is_transparent_to_state() -> None:
    """A 1 Hz reading must not churn the store — it only emits an event."""
    before = _state()
    result = reducer(
        before,
        types.MqttPublishAction(channel='a/state', payload='{"x": 1}'),
    )

    assert isinstance(result, CompleteReducerResult)
    assert result.state is before

    assert result.events is not None
    (event,) = result.events
    assert isinstance(event, types.MqttPublishEvent)
    assert event.channel == 'a/state'
    assert event.payload == '{"x": 1}'
    assert event.retain is False
    assert event.qos == 0


def test_publish_carries_retain_and_qos_through() -> None:
    """Retained/QoS-1 publishes exist; the event must not flatten them."""
    result = reducer(
        _state(),
        types.MqttPublishAction(
            channel='state/x',
            payload='1',
            retain=True,
            qos=1,
        ),
    )

    assert isinstance(result, CompleteReducerResult)
    assert result.events is not None
    (event,) = result.events
    assert event.retain is True
    assert event.qos == 1


def test_announce_request_is_transparent_to_state() -> None:
    """Contributors invalidate discovery by dispatching, not by mutating."""
    before = _state()
    result = reducer(before, types.MqttRequestAnnounceAction())

    assert isinstance(result, CompleteReducerResult)
    assert result.state is before
    assert result.events is not None
    (event,) = result.events
    assert isinstance(event, types.MqttAnnounceRequestedEvent)


def test_broker_and_toggles_are_recorded() -> None:
    """The settings UI writes through these arms."""
    broker = types.MqttBrokerConfig(
        source=types.MqttBrokerSource.EXTERNAL,
        host='broker.example.com',
        port=8883,
        username='pod',
        has_password=True,
        use_tls=True,
    )
    state = reducer(_state(), types.MqttSetBrokerAction(broker=broker))
    assert state.broker == broker

    state = reducer(state, types.MqttSetEnabledAction(is_enabled=False))
    assert state.is_enabled is False

    state = reducer(
        state,
        types.MqttSetAllowRemoteControlAction(allow_remote_control=True),
    )
    assert state.allow_remote_control is True


def test_bundled_expose_to_lan_round_trips() -> None:
    """The broker's LAN exposure is plain intent the docker service renders."""
    state = reducer(
        _state(),
        types.MqttSetBundledExposeToLanAction(expose_to_lan=True),
    )
    assert state.bundled_expose_to_lan is True

    state = reducer(
        state,
        types.MqttSetBundledExposeToLanAction(expose_to_lan=False),
    )
    assert state.bundled_expose_to_lan is False


def test_bundled_credentials_change_bumps_the_revision() -> None:
    """Each password change is a distinct transition the renderer can observe.

    The password itself never enters the store, so without this counter a
    secrets-only write would be invisible and the broker would keep serving the
    old `password_file`.
    """
    state = _state()
    first = state.bundled_credentials_revision

    state = reducer(state, types.MqttBundledCredentialsChangedAction())
    assert state.bundled_credentials_revision == first + 1

    state = reducer(state, types.MqttBundledCredentialsChangedAction())
    assert state.bundled_credentials_revision == first + 2


def test_unknown_action_is_a_no_op() -> None:
    """The slice ignores every other service's traffic."""
    before = _state()
    assert reducer(before, InitAction()) is before
