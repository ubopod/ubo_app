"""Tests for the Docker loopback ↔ LAN port-binding helpers."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable

DOCKER_SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app' / 'services' / '080-docker'

# Faithful to the current upstream compose for Hermes (loopback host IPs) and
# OpenClaw (LAN default with ${VAR:-default} interpolation whose ``:-`` must not
# be split as a token separator).
HERMES_COMPOSE = """services:
  hermes-agent:
    image: nousresearch/hermes-agent:latest
    ports:
      - "127.0.0.1:8642:8642"
  hermes-dashboard:
    image: nousresearch/hermes-dashboard:latest
    ports:
      - "127.0.0.1:9119:9119"
  hermes-webui:
    image: nousresearch/hermes-webui:latest
    ports:
      - "127.0.0.1:8787:8787"
"""

OPENCLAW_COMPOSE = """services:
  openclaw-gateway:
    image: ghcr.io/openclaw/openclaw:latest
    ports:
      - "${OPENCLAW_GATEWAY_PORT:-18789}:18789"
      - "${OPENCLAW_BRIDGE_PORT:-18790}:18790"
      - "${OPENCLAW_MSTEAMS_PORT:-3978}:3978"
  openclaw-cli:
    image: ghcr.io/openclaw/openclaw:latest
    network_mode: "service:openclaw-gateway"
"""


def _import_port_binding() -> object:
    docker_path = str(DOCKER_SERVICE_PATH)
    if docker_path not in sys.path:
        sys.path.insert(0, docker_path)
    try:
        return import_module('apps._port_binding')
    finally:
        if docker_path in sys.path:
            sys.path.remove(docker_path)


_module = _import_port_binding()
loopback_ports = cast('Callable', _module.loopback_ports)  # pyright: ignore[reportAttributeAccessIssue]
apply_compose_port_binding = cast(
    'Callable',
    _module.apply_compose_port_binding,  # pyright: ignore[reportAttributeAccessIssue]
)


# ---------------------------------------------------------------------------
# loopback_ports (single-container path)
# ---------------------------------------------------------------------------


def test_loopback_ports_int() -> None:
    """An int host port becomes a loopback (ip, port) tuple."""
    assert loopback_ports({'11434/tcp': 11434}) == {
        '11434/tcp': ('127.0.0.1', 11434),
    }


def test_loopback_ports_tuple_rebinds_ip() -> None:
    """An existing host-IP binding is rewritten to loopback."""
    assert loopback_ports({'80/tcp': ('0.0.0.0', 80)}) == {  # noqa: S104
        '80/tcp': ('127.0.0.1', 80),
    }


def test_loopback_ports_list_and_none() -> None:
    """List bindings rebind each element; None is left untouched."""
    assert loopback_ports({'53/udp': [53, 5353], 'x/tcp': None}) == {
        '53/udp': [('127.0.0.1', 53), ('127.0.0.1', 5353)],
        'x/tcp': None,
    }


# ---------------------------------------------------------------------------
# apply_compose_port_binding (composition path)
# ---------------------------------------------------------------------------


def test_hermes_loopback_is_idempotent() -> None:
    """Already-loopback Hermes ports are unchanged in loopback mode."""
    assert (
        apply_compose_port_binding(HERMES_COMPOSE, expose_to_lan=False)
        == HERMES_COMPOSE
    )


def test_hermes_lan_strips_loopback_ip() -> None:
    """LAN mode strips the 127.0.0.1 host IP so Docker uses 0.0.0.0."""
    result = apply_compose_port_binding(HERMES_COMPOSE, expose_to_lan=True)
    assert '"8642:8642"' in result
    assert '"9119:9119"' in result
    assert '"8787:8787"' in result
    assert '127.0.0.1' not in result


def test_openclaw_loopback_prepends_ip_preserving_var() -> None:
    """Loopback prepends 127.0.0.1 while keeping the ${VAR:-default} token."""
    result = apply_compose_port_binding(OPENCLAW_COMPOSE, expose_to_lan=False)
    assert '"127.0.0.1:${OPENCLAW_GATEWAY_PORT:-18789}:18789"' in result
    assert '"127.0.0.1:${OPENCLAW_BRIDGE_PORT:-18790}:18790"' in result
    assert '"127.0.0.1:${OPENCLAW_MSTEAMS_PORT:-3978}:3978"' in result
    # The cli service has no ports and must be untouched.
    assert 'network_mode: "service:openclaw-gateway"' in result


def test_openclaw_lan_is_default_noop() -> None:
    """LAN mode leaves OpenClaw's variable port mappings unchanged."""
    assert (
        apply_compose_port_binding(OPENCLAW_COMPOSE, expose_to_lan=True)
        == OPENCLAW_COMPOSE
    )


def test_round_trip_openclaw() -> None:
    """Loopback → LAN restores the original OpenClaw compose."""
    loop = apply_compose_port_binding(OPENCLAW_COMPOSE, expose_to_lan=False)
    back = apply_compose_port_binding(loop, expose_to_lan=True)
    assert back == OPENCLAW_COMPOSE


def test_round_trip_hermes() -> None:
    """LAN → loopback restores the original Hermes compose."""
    lan = apply_compose_port_binding(HERMES_COMPOSE, expose_to_lan=True)
    back = apply_compose_port_binding(lan, expose_to_lan=False)
    assert back == HERMES_COMPOSE


def test_proto_suffix_preserved() -> None:
    """A /tcp protocol suffix survives the host-IP rewrite."""
    compose = 'services:\n  s:\n    ports:\n      - "8642:8642/tcp"\n'
    result = apply_compose_port_binding(compose, expose_to_lan=False)
    assert '"127.0.0.1:8642:8642/tcp"' in result


def test_unquoted_entry() -> None:
    """An unquoted ports entry is rewritten too."""
    compose = 'services:\n  s:\n    ports:\n      - 8642:8642\n'
    result = apply_compose_port_binding(compose, expose_to_lan=False)
    assert '- 127.0.0.1:8642:8642' in result


def test_non_ports_volume_mapping_untouched() -> None:
    """A volumes block sharing colon syntax is left alone."""
    compose = (
        'services:\n  s:\n'
        '    volumes:\n      - ./data:/app/data\n'
        '    ports:\n      - "9119:9119"\n'
    )
    result = apply_compose_port_binding(compose, expose_to_lan=False)
    assert '- ./data:/app/data' in result
    assert '"127.0.0.1:9119:9119"' in result
