"""Web-dashboard forms must not name a field with a reserved key.

The web UI builds ``InputResult.data`` from the raw submitted form after
removing its own control keys::

    id = data.pop('id')
    value = data.pop('value', '')

A field named one of those is silently swallowed — the form submits, the flow
resolves, and the handler reads an empty string. That looked exactly like the
user mistyping an address.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WEB_UI_SETUP = REPO / 'ubo_app' / 'services' / '090-web-ui' / 'setup.py'
SERVICES = REPO / 'ubo_app' / 'services'


def _reserved_keys() -> set[str]:
    """Read the control keys the web UI removes, rather than hardcoding them."""
    source = WEB_UI_SETUP.read_text()
    popped = set(re.findall(r"data\.pop\(\s*'([^']+)'", source))
    read = set(re.findall(r"data\[\s*'([^']+)'\s*\]\s*==", source))
    return popped | read


def _declared_field_names() -> list[tuple[Path, str]]:
    """Collect every ``InputFieldDescription(name=...)`` literal in the services."""
    found: list[tuple[Path, str]] = []
    for path in SERVICES.rglob('*.py'):
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError):
            continue
        found.extend(
            (path, str(keyword.value.value))
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == 'InputFieldDescription'
            for keyword in node.keywords
            if keyword.arg == 'name' and isinstance(keyword.value, ast.Constant)
        )
    return found


def test_the_reserved_keys_are_still_what_we_think() -> None:
    """Guard the guard: if the web UI stops popping these, revisit this test."""
    assert _reserved_keys() >= {'action', 'id', 'value'}


def test_no_input_field_uses_a_reserved_key() -> None:
    """A field named like a control key never reaches its handler."""
    reserved = _reserved_keys()
    fields = _declared_field_names()

    assert fields, 'no input fields found; the AST scan is not matching anything'

    offenders = [
        f'{path.relative_to(REPO)}: name={name!r}'
        for path, name in fields
        if name in reserved
    ]

    assert not offenders, (
        'these form fields are swallowed by the web dashboard: '
        + '; '.join(offenders)
    )
