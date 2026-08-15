"""Tests for the pod's MQTT topic layout.

Topics are the wire contract with every other client on the broker, so they are
pinned literally rather than rebuilt from the same f-strings.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.service_loader import load_service_modules

_M = load_service_modules(
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '050-mqtt',
    'topics',
)
topics = _M[0]


def test_topics_are_namespaced_by_serial() -> None:
    """Every topic carries the pod's serial, so two pods can share a broker."""
    assert topics.discovery_topic('abc') == 'homeassistant/device/ubo_abc/config'
    assert topics.availability_topic('abc') == 'ubo/abc/availability'
    assert topics.channel_topic('abc', 'bme280_0x76/state') == (
        'ubo/abc/bme280_0x76/state'
    )


def test_sanitize_reduces_to_topic_safe_characters() -> None:
    """A serial number is not guaranteed to be topic-safe."""
    assert topics.sanitize('AB-12:34') == 'ab_12_34'
    assert topics.sanitize('already_safe') == 'already_safe'


@pytest.mark.parametrize(
    'channel',
    ['state/sensors', 'a', 'cmd/audio:play_chime', 'bme280_0x76/state'],
)
def test_ordinary_channels_are_accepted(channel: str) -> None:
    """A producer's relative channel is published under the pod's namespace."""
    assert topics.is_relative(channel) is True


@pytest.mark.parametrize(
    'channel',
    [
        '',  # nothing to publish to
        '/absolute',  # escapes the namespace
        'trailing/',  # renders an empty final segment
        'double//slash',
        'wild/+/card',  # a subscription pattern, not a topic
        'wild/#',
        '../escape',
    ],
)
def test_unsafe_channels_are_rejected(channel: str) -> None:
    """The bridge owns the `ubo/<serial>/` prefix and will not be escaped.

    A producer that tries is rejected rather than silently rewritten — this is
    the check that keeps `MqttPublishAction`, which is reachable over gRPC,
    from publishing anywhere on the broker.
    """
    assert topics.is_relative(channel) is False
