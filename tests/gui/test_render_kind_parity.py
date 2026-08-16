"""Every render kind the pod can open must render on every client.

A `kind` the web UI does not know falls through to its default branch and draws
an empty box — which is exactly how the sensor readings page looked on the web
while the pod screen showed the table. Nothing else pins the registries
together, so this reads the files rather than importing them: the Kivy widgets
live in the GUI client's own package (and venv), the web client is TypeScript,
the TUI dispatches in an `if`/`elif` chain rather than a registry, and the LVGL
client is C.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
KIVY_WIDGETS = (
    REPO_ROOT / 'ubo_app' / 'gui' / 'ubo_gui_client' / 'widgets' / '__init__.py'
)
WEB_RENDER_VIEW = (
    REPO_ROOT
    / 'ubo_app'
    / 'services'
    / '090-web-ui'
    / 'web-app'
    / 'src'
    / 'components'
    / 'RenderView.tsx'
)
TUI_RENDER_VIEW = REPO_ROOT / 'ubo_app' / 'tui' / 'ubo_tui' / 'views' / 'render.py'
LVGL_RENDER_VIEW = REPO_ROOT / 'ubo_lvgl' / 'src' / 'views' / 'view_render.c'


def _kivy_render_kinds() -> set[str]:
    """Read the keys of `GENERIC_RENDER_WIDGETS`, without importing Kivy."""
    module = ast.parse(KIVY_WIDGETS.read_text())
    for node in ast.walk(module):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == 'GENERIC_RENDER_WIDGETS'
            and isinstance(node.value, ast.Dict)
        ):
            return {
                key.value
                for key in node.value.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
    msg = f'GENERIC_RENDER_WIDGETS not found in {KIVY_WIDGETS}'
    raise AssertionError(msg)


def _web_render_kinds() -> set[str]:
    """Read the `case "…":` labels of the web client's render dispatcher."""
    return set(re.findall(r'case "([^"]+)":', WEB_RENDER_VIEW.read_text()))


def _tui_render_kinds() -> set[str]:
    """Read the `kind == "…"` / `kind in {…}` conditions of the TUI dispatcher.

    The TUI has no registry dict, so the dispatch conditions themselves are the
    source of truth.
    """
    source = TUI_RENDER_VIEW.read_text()
    kinds = set(re.findall(r'kind == "([^"]+)"', source))
    for group in re.findall(r'kind in \{([^}]+)\}', source):
        kinds.update(re.findall(r'"([^"]+)"', group))
    return kinds


def _lvgl_render_kinds() -> set[str]:
    """Read the `strcmp(kind, "…") == 0` labels of the C dispatcher.

    Like the TUI it has no registry, and unlike the TUI an unknown kind is not
    even a silent blank: it draws the kind string itself as a placeholder, which
    is how the sensor readings page read "readings" on the LVGL screen.
    """
    return set(re.findall(r'strcmp\(kind, "([^"]+)"\)', LVGL_RENDER_VIEW.read_text()))


def test_the_web_client_renders_every_kind_the_kivy_client_does() -> None:
    """Otherwise the web UI silently draws an empty page for that kind."""
    assert _kivy_render_kinds() - _web_render_kinds() == set()


def test_the_tui_client_renders_every_kind_the_kivy_client_does() -> None:
    """Otherwise the TUI falls through to "(no text content)" for that kind."""
    assert _kivy_render_kinds() - _tui_render_kinds() == set()


def test_the_lvgl_client_renders_every_kind_the_kivy_client_does() -> None:
    """Otherwise the LVGL screen shows the kind name as its own placeholder."""
    assert _kivy_render_kinds() - _lvgl_render_kinds() == set()
