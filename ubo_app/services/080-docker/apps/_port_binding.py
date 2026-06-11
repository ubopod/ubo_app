"""Host port-binding rewrites for the loopback ↔ LAN exposure toggle.

Two binding mechanisms exist in this service and both are covered here:

- single containers pass a ``ports`` dict to ``docker.containers.run`` —
  :func:`loopback_ports` rewrites it to bind ``127.0.0.1``;
- compositions publish their ports in an on-disk ``docker-compose.yml`` —
  :func:`apply_compose_port_binding` rewrites the short-syntax ``ports:``
  entries.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

LOOPBACK_IP = '127.0.0.1'
# Literal host IPs we own and may add/strip. An explicit ``0.0.0.0`` (all
# interfaces) or ``127.0.0.1`` is rewritten; any other/variable host IP is left
# untouched so we never clobber a deliberate binding.
_LITERAL_BIND_IPS = (LOOPBACK_IP, '0.0.0.0')  # noqa: S104

PortSpec = int | list[int] | tuple[str, int] | None
LoopbackSpec = tuple[str, int] | list[tuple[str, int] | int] | None

# A single port-mapping token: a number/IP (``18789``, ``127.0.0.1``) or a
# compose variable reference (``${OPENCLAW_GATEWAY_PORT:-18789}``). The variable
# form is matched atomically so the ``:-`` default-value separator inside it is
# never mistaken for the ``:`` that separates mapping tokens.
_TOKEN = r'(?:\$\{[^}]*\}|[0-9.]+)'  # noqa: S105
_PROTO = r'(?:/\w+)?'

# A short-syntax ports value: ``[host_ip:]published:target[/proto]``.
_PORT_VALUE_RE = re.compile(
    rf'^(?P<a>{_TOKEN})(?::(?P<b>{_TOKEN}))?(?::(?P<c>{_TOKEN}))?'
    rf'(?P<proto>{_PROTO})$',
)

# A short-syntax ports list item, e.g. ``      - "9119:9119"``.
_PORT_ITEM_RE = re.compile(
    r'^(?P<prefix>\s*-\s*)(?P<q>["\']?)(?P<value>[^"\'#]+?)(?P=q)'
    r'(?P<suffix>\s*(?:#.*)?)$',
)

_PORTS_KEY_RE = re.compile(r'^(?P<indent>\s*)ports:\s*(?:#.*)?$')


def loopback_ports(ports: Mapping[str, PortSpec]) -> dict[str, LoopbackSpec]:
    """Return a copy of a container ``ports`` dict bound to loopback only."""
    result: dict[str, LoopbackSpec] = {}
    for key, value in ports.items():
        if isinstance(value, int):
            result[key] = (LOOPBACK_IP, value)
        elif isinstance(value, tuple):
            result[key] = (LOOPBACK_IP, value[1])
        elif isinstance(value, list):
            result[key] = [
                (LOOPBACK_IP, item) if isinstance(item, int) else item
                for item in value
            ]
        else:
            result[key] = value
    return result


def _rebind_value(value: str, *, expose_to_lan: bool) -> str:
    """Rewrite a single ``host:container`` mapping's host binding."""
    match = _PORT_VALUE_RE.match(value)
    if match is None:
        return value
    tokens = [
        token
        for token in (match.group('a'), match.group('b'), match.group('c'))
        if token is not None
    ]
    proto = match.group('proto')

    if len(tokens) < 2:  # noqa: PLR2004 - bare container port; nothing to bind
        return value
    if len(tokens) == 2:  # noqa: PLR2004
        host_ip, (published, target) = None, tokens
    else:
        host_ip, published, target = tokens

    if expose_to_lan:
        # Drop only a literal loopback/all-interfaces host IP so Docker falls
        # back to its 0.0.0.0 default; keep an explicit variable host IP.
        if host_ip in _LITERAL_BIND_IPS:
            host_ip = None
    else:
        host_ip = LOOPBACK_IP

    mapping = (
        f'{published}:{target}'
        if host_ip is None
        else f'{host_ip}:{published}:{target}'
    )
    return f'{mapping}{proto}'


def _rebind_item(line: str, *, expose_to_lan: bool) -> str:
    match = _PORT_ITEM_RE.match(line)
    if match is None:
        return line
    new_value = _rebind_value(match.group('value'), expose_to_lan=expose_to_lan)
    return (
        f'{match.group("prefix")}{match.group("q")}{new_value}'
        f'{match.group("q")}{match.group("suffix")}'
    )


def apply_compose_port_binding(text: str, *, expose_to_lan: bool) -> str:
    """Rewrite host bindings of short-syntax ``ports:`` entries in a compose file.

    Loopback mode prepends/forces ``127.0.0.1`` on every published port; LAN
    mode strips a literal ``127.0.0.1``/``0.0.0.0`` host IP so Docker uses its
    ``0.0.0.0`` default. Comments, quoting, indentation, long-syntax entries
    and non-``ports:`` lines are left untouched.
    """
    out: list[str] = []
    in_ports = False
    ports_indent = 0
    for raw_line in text.splitlines(keepends=True):
        line, newline = raw_line, ''
        if line.endswith('\r\n'):
            line, newline = line[:-2], '\r\n'
        elif line.endswith('\n'):
            line, newline = line[:-1], '\n'

        if (key_match := _PORTS_KEY_RE.match(line)) is not None:
            in_ports = True
            ports_indent = len(key_match.group('indent'))
            out.append(raw_line)
            continue

        if in_ports:
            stripped = line.strip()
            indent = len(line) - len(line.lstrip())
            if stripped == '':
                out.append(raw_line)
                continue
            if stripped.startswith('-') and indent > ports_indent:
                out.append(_rebind_item(line, expose_to_lan=expose_to_lan) + newline)
                continue
            # Anything else ends the ports block.
            in_ports = False

        out.append(raw_line)
    return ''.join(out)
