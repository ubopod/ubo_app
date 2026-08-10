"""Tests for parsing ``docker compose ps -a --format json``.

The output shape depends on the Compose version and nothing in this repo pins
one, so both shapes are asserted rather than assumed.
"""

from __future__ import annotations

import json
import sys
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

DOCKER_SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app' / 'services' / '080-docker'


def _module() -> ModuleType:
    """Import the parser the way the service loader does."""
    docker_path = str(DOCKER_SERVICE_PATH)
    if docker_path not in sys.path:
        sys.path.insert(0, docker_path)
    try:
        return import_module('compose_ps')
    finally:
        if docker_path in sys.path:
            sys.path.remove(docker_path)


def _entry(service: str, state: str, **extra: object) -> dict[str, object]:
    return {'Service': service, 'State': state, 'Health': '', 'ExitCode': 0, **extra}


def test_parses_the_json_array_shape() -> None:
    """Compose 2.21 and later emit a single array."""
    module = _module()

    payload = json.dumps([_entry('db', 'running'), _entry('web', 'exited')])
    services = module.parse_compose_ps(payload)

    assert [service.service for service in services] == ['db', 'web']
    assert services[0].state == 'running'


def test_parses_the_json_lines_shape() -> None:
    """Compose before 2.21 emits one object per line, with no enclosing array."""
    module = _module()

    payload = '\n'.join(
        json.dumps(entry)
        for entry in (_entry('db', 'running'), _entry('web', 'restarting'))
    )
    services = module.parse_compose_ps(payload)

    assert [service.service for service in services] == ['db', 'web']
    assert services[1].state == 'restarting'


def test_empty_output_parses_to_nothing() -> None:
    """A stack that was never created lists no containers."""
    module = _module()

    assert module.parse_compose_ps('') == ()
    assert module.parse_compose_ps('   \n  ') == ()


def test_a_malformed_line_does_not_cost_the_rest() -> None:
    """One unreadable line must not discard the whole report."""
    module = _module()

    payload = f'{json.dumps(_entry("db", "running"))}\nnot json\n'
    services = module.parse_compose_ps(payload)

    assert [service.service for service in services] == ['db']


def test_restarting_and_failed_services_are_named() -> None:
    """`restarting` is the steady state of a crash loop under restart policies."""
    module = _module()

    services = module.parse_compose_ps(
        json.dumps(
            [
                _entry('db', 'running'),
                _entry('web', 'restarting'),
                _entry('worker', 'exited', ExitCode=1),
                _entry('proxy', 'running', Health='unhealthy'),
            ],
        ),
    )

    assert module.failing_services(services) == ('web', 'worker', 'proxy')


def test_a_clean_one_shot_exit_is_not_a_failure() -> None:
    """Init containers finish with code 0; several bundled stacks have them."""
    module = _module()

    services = module.parse_compose_ps(
        json.dumps([_entry('init', 'exited'), _entry('app', 'running')]),
    )

    assert module.failing_services(services) == ()
    assert module.has_running(services) is True


def test_a_wholly_stopped_stack_is_not_running() -> None:
    """Nothing up means CREATED, not STARTING."""
    module = _module()

    services = module.parse_compose_ps(
        json.dumps([_entry('db', 'exited'), _entry('web', 'exited')]),
    )

    assert module.has_running(services) is False


def test_a_crash_looping_stack_still_counts_as_running() -> None:
    """A restarting container is trying to come up, not stopped.

    Reporting CREATED here is what offered the user a Start button for a stack
    that was already starting, over and over.
    """
    module = _module()

    services = module.parse_compose_ps(json.dumps([_entry('web', 'restarting')]))

    assert module.has_running(services) is True
    assert module.failing_services(services) == ('web',)
