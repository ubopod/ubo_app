"""Tests for broker config persistence.

`MqttState` builds its broker default at *class-definition* time, so anything
`_parse_broker` raises is not a bad config — it is an import-time crash that
takes the whole app down. These tests pin that a hand-edited, truncated or
downgraded ``state.json`` degrades to the defaults instead.

They also pin the write side, because the round-trip only works if
`serialize_broker` emits exactly what `_parse_broker` reads back.
"""

from __future__ import annotations

import json

import pytest

from ubo_app.store.services.mqtt import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    MqttBrokerConfig,
    MqttBrokerSource,
    _parse_broker,
    _parse_opt_in,
    persist_broker,
    serialize_broker,
)

EXTERNAL = MqttBrokerConfig(
    source=MqttBrokerSource.EXTERNAL,
    host='homeassistant.local',
    port=8883,
    username='ubo',
    has_password=True,
    use_tls=True,
    ca_cert_path='/etc/ssl/certs/ha.pem',
)


def test_an_external_broker_round_trips() -> None:
    """Everything the user typed must survive a reboot — except the password."""
    assert serialize_broker(EXTERNAL) == {
        'source': 'external',
        'host': 'homeassistant.local',
        'port': 8883,
        'username': 'ubo',
        'has_password': True,
        'use_tls': True,
        'ca_cert_path': '/etc/ssl/certs/ha.pem',
    }
    assert _parse_broker(json.dumps(serialize_broker(EXTERNAL))) == EXTERNAL


def test_what_is_persisted_is_a_plain_json_string() -> None:
    """Handing the `Immutable` over instead would write a dill `_type` marker.

    `_parse_broker` reads plain JSON, so the two would silently stop agreeing.
    """
    persisted = persist_broker(EXTERNAL)

    assert isinstance(persisted, str)
    assert json.loads(persisted) == serialize_broker(EXTERNAL)
    assert _parse_broker(persisted) == EXTERNAL


def test_a_stored_mapping_is_read_as_well_as_a_string() -> None:
    """The persistent store hands back whatever `json.loads` produced."""
    assert _parse_broker(serialize_broker(EXTERNAL)) == EXTERNAL


@pytest.mark.parametrize(
    'stored',
    [
        pytest.param('{"source": "external"', id='truncated-json'),
        pytest.param('not json at all', id='not-json'),
        pytest.param('[]', id='not-an-object'),
        pytest.param('null', id='null'),
        pytest.param(42, id='not-a-string-or-mapping'),
        pytest.param('{"source": "carrier-pigeon"}', id='unknown-source'),
        pytest.param('{}', id='no-source'),
    ],
)
def test_an_unusable_document_falls_back_to_defaults(stored: object) -> None:
    """A crash here is an import-time crash, not a bad setting."""
    assert _parse_broker(stored) == MqttBrokerConfig()


@pytest.mark.parametrize(
    'port',
    [
        pytest.param(0, id='below-range'),
        pytest.param(99999, id='above-range'),
        pytest.param('1883', id='string'),
        pytest.param('nonsense', id='not-a-number'),
        pytest.param(None, id='null'),
    ],
)
def test_an_out_of_range_port_falls_back(port: object) -> None:
    """A port outside 1..65535 would fail deep inside aiomqtt instead."""
    parsed = _parse_broker({'source': 'external', 'host': 'ha.local', 'port': port})

    assert parsed.port == (1883 if port == '1883' else DEFAULT_PORT)
    assert parsed.host == 'ha.local'


def test_bundled_ignores_stale_external_fields() -> None:
    """A bundled broker is the loopback Mosquitto by definition.

    Switching back from an external broker must not leave the host, credentials
    or TLS settings behind — otherwise "bundled" could point anywhere.
    """
    parsed = _parse_broker(
        {
            'source': 'bundled',
            'host': 'attacker.example.com',
            'port': 8883,
            'username': 'ubo',
            'has_password': True,
            'use_tls': True,
            'ca_cert_path': '/tmp/evil.pem',  # noqa: S108
        },
    )

    assert parsed == MqttBrokerConfig()
    assert parsed.host == DEFAULT_HOST
    assert parsed.port == DEFAULT_PORT
    assert parsed.username == ''
    assert parsed.has_password is False
    assert parsed.use_tls is False


@pytest.mark.parametrize(
    ('stored', 'expected'),
    [
        pytest.param(True, True, id='true'),
        pytest.param(False, False, id='false'),
        pytest.param('false', False, id='the-string-false'),
        pytest.param('true', False, id='the-string-true'),
        pytest.param(1, False, id='one'),
        pytest.param(0, False, id='zero'),
        pytest.param(None, False, id='null'),
        pytest.param([], False, id='empty-list'),
        pytest.param({'enabled': True}, False, id='object'),
    ],
)
def test_an_opt_in_flag_is_parsed_strictly(
    stored: object,
    expected: bool,  # noqa: FBT001
) -> None:
    """Anything but a real `True` has to read as off.

    `read_from_persistent_store` returns whatever JSON held, and a non-empty
    string is truthy — a hand-edited `"false"` would *enable* remote control on
    every subsequent check. A security-sensitive flag must fail closed.
    """
    assert _parse_opt_in(stored) is expected
