"""A service must not register two setting apps under the same key.

``register_setting_app`` derives the registry key from the dispatching
service and the action's optional ``key`` field::

    key = f'{action.service}:'
    if action.key is not None:
        key += action.key

so two ``RegisterSettingAppAction``s from one service that both omit ``key``
collapse onto ``'<service>:'``. The second one raises ``ValueError`` inside
the reducer, and because reducers run from the store heartbeat the traceback
is only *logged* — the app keeps running and the entry silently never appears
in its settings category.

That is exactly how the localization service lost its "Location" entry: both
of its registrations omitted ``key``, so only "Language" survived.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parents[2]
SERVICES = REPO / 'ubo_app' / 'services'

ACTION_NAME = 'RegisterSettingAppAction'


class Registration(NamedTuple):
    """One ``RegisterSettingAppAction(...)`` call site found in the sources."""

    service: str
    key: str | None
    label: str
    location: str

    @property
    def registry_key(self) -> str:
        """Mirror the key ``register_setting_app`` builds for this call site."""
        return f'{self.service}:{self.key or ""}'


def _constant(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _registrations() -> list[Registration]:
    """Collect every setting-app registration declared under the services."""
    found: list[Registration] = []
    for path in sorted(SERVICES.rglob('*.py')):
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == ACTION_NAME
            ):
                continue
            keywords = {keyword.arg: keyword.value for keyword in node.keywords}
            found.append(
                Registration(
                    service=path.relative_to(SERVICES).parts[0],
                    key=_constant(keywords.get('key')),
                    label=_constant(keywords.get('label')) or '?',
                    location=(
                        f'{path.relative_to(REPO).as_posix()}:{node.lineno}'
                    ),
                ),
            )
    return found


def test_the_scan_still_finds_registrations() -> None:
    """Guard the guard: a rename must not make the check below vacuous."""
    registrations = _registrations()
    assert len(registrations) > 1
    assert any(registration.key is not None for registration in registrations)
    assert any(registration.key is None for registration in registrations)


def test_no_service_registers_two_setting_apps_with_the_same_key() -> None:
    """Colliding keys make the loser vanish from its settings category."""
    by_key: defaultdict[str, list[Registration]] = defaultdict(list)
    for registration in _registrations():
        by_key[registration.registry_key].append(registration)

    collisions = {
        key: entries for key, entries in by_key.items() if len(entries) > 1
    }

    assert not collisions, '\n'.join(
        f'{key!r} is registered {len(entries)} times: {entries}'
        for key, entries in sorted(collisions.items())
    )
