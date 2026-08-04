"""Tests for the MQTT settings menu's decision functions.

Only the pure parts are covered here — the parts where a mistake is silent.
`resolve_password` in particular: get it wrong and a user who edits the host
loses the password they never touched, with nothing to indicate it happened.

The store types are imported normally, not through the service loader: the
loader leaves ``ubo_app.*`` alone, so the `MqttBrokerSource` the menu compares
against and the one constructed here are the same class object.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.service_loader import load_service_modules
from ubo_app.store.services import mqtt as types

(menu,) = load_service_modules(
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '050-mqtt',
    'menu',
)

_SETTINGS = ('main', 'settings', 'Network', 'mqtt:')


@pytest.mark.parametrize(
    ('data', 'had_password', 'expected'),
    [
        pytest.param(
            {'password': 'hunter2'},
            False,
            ('hunter2', True),
            id='a-new-password-is-written',
        ),
        pytest.param(
            {'password': '  hunter2  '},
            False,
            ('hunter2', True),
            id='a-new-password-is-stripped',
        ),
        pytest.param(
            {'password': ''},
            True,
            (None, True),
            id='blank-keeps-the-existing-password',
        ),
        pytest.param(
            {},
            True,
            (None, True),
            id='an-absent-field-keeps-the-existing-password',
        ),
        pytest.param(
            {'password': ''},
            False,
            (None, False),
            id='blank-with-none-stored-stays-anonymous',
        ),
        pytest.param(
            {'password': '', 'clear_password': 'on'},
            True,
            (None, False),
            id='the-checkbox-clears-it',
        ),
        pytest.param(
            {'password': 'hunter2', 'clear_password': 'on'},
            True,
            (None, False),
            id='clearing-beats-a-typed-password',
        ),
    ],
)
def test_resolve_password(
    data: dict[str, str],
    had_password: bool,  # noqa: FBT001
    expected: tuple[str | None, bool],
) -> None:
    """Blank must mean "leave it alone", never "erase it".

    The field is never prefilled with the real secret, so a user editing only
    the host submits an empty password box every time.
    """
    assert menu.resolve_password(data, had_password=had_password) == expected


@pytest.mark.parametrize(
    ('path', 'expected'),
    [
        pytest.param(_SETTINGS, 'mqtt:settings', id='settings-page'),
        pytest.param(
            (*_SETTINGS, 'mqtt:broker'),
            'mqtt:broker',
            id='broker-submenu-wins-over-the-settings-page',
        ),
        pytest.param((*_SETTINGS, 'unknown'), 'mqtt:settings', id='unknown-subpage'),
        pytest.param(('main', 'settings', 'Network'), None, id='too-short'),
        pytest.param(
            ('main', 'settings', 'Network', 'wifi:'),
            None,
            id='another-service',
        ),
        pytest.param((), None, id='empty'),
    ],
)
def test_path_matcher(path: tuple[str, ...], expected: str | None) -> None:
    """The deeper page must be checked first, or it is never reachable."""
    assert menu._path_matcher(path) == expected  # noqa: SLF001


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        pytest.param('on', True, id='web-ui-checked'),
        pytest.param('true', True, id='true'),
        pytest.param('  ON  ', True, id='padded-and-uppercase'),
        pytest.param('', False, id='empty'),
        pytest.param(None, False, id='absent'),
        pytest.param('off', False, id='off'),
    ],
)
def test_is_checkbox_on(value: str | None, expected: bool) -> None:  # noqa: FBT001
    """The web UI submits `on`; everything else is unchecked."""
    assert menu._is_checkbox_on(value) is expected  # noqa: SLF001


def test_a_bundled_broker_is_described_without_an_address() -> None:
    """Its address is an implementation detail the user cannot change."""
    assert menu._describe_broker(types.MqttBrokerConfig()) == 'Bundled broker'  # noqa: SLF001


def test_an_external_broker_is_described_by_where_it_is() -> None:
    """The sub-heading is how the user confirms they typed the right host."""
    broker = types.MqttBrokerConfig(
        source=types.MqttBrokerSource.EXTERNAL,
        host='homeassistant.local',
        port=8883,
        username='ubo',
    )

    assert menu._describe_broker(broker) == 'ubo@homeassistant.local:8883'  # noqa: SLF001


def test_an_anonymous_external_broker_omits_the_username() -> None:
    """`@host` with nothing before it would just look broken."""
    broker = types.MqttBrokerConfig(
        source=types.MqttBrokerSource.EXTERNAL,
        host='192.168.1.10',
    )

    assert menu._describe_broker(broker) == '192.168.1.10:1883'  # noqa: SLF001
