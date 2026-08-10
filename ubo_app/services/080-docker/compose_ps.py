"""Parsing for ``docker compose ps --format json``.

Pure, so it can be tested without a daemon. Kept separate from
``docker_composition`` for the same reason ``log_format`` is separate from
``docker_logs``: that module imports the store at scope and cannot be loaded
from the unit tier.
"""

from __future__ import annotations

import json
from typing import NamedTuple


class ComposeService(NamedTuple):
    """One container in a composition, as ``compose ps`` describes it."""

    service: str
    state: str
    health: str
    exit_code: int


def parse_compose_ps(output: str) -> tuple[ComposeService, ...]:
    """Parse ``docker compose ps -a --format json``.

    The output shape depends on the Compose version: below 2.21 it is JSON
    Lines, one object per line; from 2.21 it is a single JSON array. Nothing in
    this repo pins a Compose version — ``install_docker`` takes whatever the
    distro package provides — so field devices span both and this accepts either.
    """
    text = output.strip()
    if not text:
        return ()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError:
                # One malformed line must not cost us the rest of the report.
                continue

    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        return ()

    return tuple(
        ComposeService(
            service=str(entry.get('Service') or ''),
            state=str(entry.get('State') or ''),
            health=str(entry.get('Health') or ''),
            exit_code=int(entry.get('ExitCode') or 0),
        )
        for entry in parsed
        if isinstance(entry, dict)
    )


def has_running(services: tuple[ComposeService, ...]) -> bool:
    """Whether any container in the stack is up.

    ``restarting`` counts: a container in restart backoff is trying to come up,
    not stopped.
    """
    return any(
        service.state in ('running', 'restarting') for service in services
    )


def failing_services(services: tuple[ComposeService, ...]) -> tuple[str, ...]:
    """Name the services that cannot stay up.

    ``restarting`` and ``unhealthy`` are unambiguous: the daemon is actively
    retrying, or the service's own healthcheck says it is sick. Both stand on
    their own.

    A nonzero ``exited`` code does not. ``docker compose stop`` sends SIGTERM,
    so a service that does not trap it exits 143 — and one that has to be killed
    exits 137 — on a perfectly deliberate stop. It only means something while
    the rest of the stack is still up, which is the partial-failure case: these
    siblings are serving, this one fell over. Once nothing is running, the whole
    stack was wound down and there is nobody to blame.

    A clean ``exited`` with code 0 is never a failure: that is how the one-shot
    init containers in several bundled stacks finish.
    """
    stack_is_up = has_running(services)
    return tuple(
        service.service
        for service in services
        if service.state == 'restarting'
        or service.health == 'unhealthy'
        or (stack_is_up and service.state == 'exited' and service.exit_code != 0)
    )
