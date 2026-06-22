"""Navigation contract for the Voice Shortcuts → Vosk model deep-link.

The Accessibility "Voice Shortcuts" menu warns when the Vosk model isn't
downloaded and offers a "Download Vosk Model" item whose handler
(``speech-recognition:open-vosk-models`` in
``services/090-speech-recognition/setup.py``) navigates to the assistant's STT
settings page so the model downloader is reachable.

The assistant path matcher
(``services/090-assistant/setup.py`` ``_assistant_path_matcher``) only resolves
the Vosk drill-down when the navigation path starts with
``('main', 'settings', 'Assistant', …)``. A single push from the Accessibility
context would build a wrong-prefix path and dead-end, so the handler pops to the
root and rebuilds the canonical chain. These tests pin that the rebuilt path
lands exactly where the assistant matcher expects — a regression here (e.g.
dropping the leading ``'main'`` frame) would silently break the deep-link.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.store.core.types import (
    StackPopToRootAction,
    StackPushMenuAction,
)

if TYPE_CHECKING:
    from tests.navigation.conftest import ReducerRunner

# Mirrors the action sequence dispatched by the
# 'speech-recognition:open-vosk-models' handler in the speech-recognition
# service. Kept in sync with that handler by intent.
_DEEP_LINK_ACTIONS = (
    StackPopToRootAction(),
    StackPushMenuAction(menu_key='main'),
    StackPushMenuAction(menu_key='settings'),
    StackPushMenuAction(menu_key='Assistant'),
    StackPushMenuAction(menu_key='assistant:stt'),
)

# The prefix the assistant path matcher requires to resolve the Vosk children.
_ASSISTANT_PREFIX = ('main', 'settings', 'Assistant')
_ASSISTANT_STT_PATH = ('main', 'settings', 'Assistant', 'assistant:stt')


def _run_deep_link(nav: ReducerRunner) -> None:
    for action in _DEEP_LINK_ACTIONS:
        nav.dispatch(action)


class TestVoskModelDeepLink:
    """The deep-link rebuilds the canonical Assistant STT navigation path."""

    def test_from_root_lands_on_assistant_stt(self, nav: ReducerRunner) -> None:
        """The sequence lands on the Assistant STT page from a fresh root."""
        _run_deep_link(nav)
        assert nav.state.path == _ASSISTANT_STT_PATH

    def test_path_prefix_matches_assistant_matcher(
        self,
        nav: ReducerRunner,
    ) -> None:
        """The path prefix is exactly what the assistant matcher requires."""
        _run_deep_link(nav)
        assert nav.state.path[:3] == _ASSISTANT_PREFIX

    def test_resets_wrong_prefix_accessibility_context(
        self,
        nav: ReducerRunner,
    ) -> None:
        """A deep Accessibility (wrong-prefix) stack is reset, not appended to."""
        # Simulate the user standing inside Voice Shortcuts under Accessibility.
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushMenuAction(menu_key='settings'))
        nav.dispatch(StackPushMenuAction(menu_key='Accessibility'))
        nav.dispatch(StackPushMenuAction(menu_key='speech-recognition:commands'))
        assert nav.state.path[:3] != _ASSISTANT_PREFIX

        _run_deep_link(nav)

        # Pop-to-root cleared the Accessibility frames; no leftover prefix.
        assert nav.state.path == _ASSISTANT_STT_PATH
