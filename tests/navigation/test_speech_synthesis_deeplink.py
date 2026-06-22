"""Navigation contract for the Screen Reader → TTS setup deep-link.

When the screen reader is enabled with no TTS engine configured, the
speech-synthesis service raises a "Set up" notification whose action
(``_warn_no_tts_configured`` in ``services/010-speech-synthesis/setup.py``)
navigates to the assistant's Text-to-Speech settings page so an engine can be
configured / a voice downloaded.

Like the assistant's other sub-pages, the TTS drill-down (Piper / Kokoro voice
download) only resolves when the navigation path starts with
``('main', 'settings', 'Assistant', …)`` (``_assistant_path_matcher`` in
``services/090-assistant/setup.py``). The notification action therefore pops to
the root and rebuilds the canonical chain — including the leading ``'main'``
frame. These tests pin that the rebuilt path lands where the assistant matcher
expects; dropping the ``'main'`` frame would land on the TTS menu but dead-end
every child page.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.store.core.types import (
    StackPopToRootAction,
    StackPushMenuAction,
)

if TYPE_CHECKING:
    from tests.navigation.conftest import ReducerRunner

# Mirrors the store_action sequence in the screen reader's "Set up"
# notification (speech-synthesis service). Kept in sync by intent.
_DEEP_LINK_ACTIONS = (
    StackPopToRootAction(),
    StackPushMenuAction(menu_key='main'),
    StackPushMenuAction(menu_key='settings'),
    StackPushMenuAction(menu_key='Assistant'),
    StackPushMenuAction(menu_key='assistant:tts'),
)

# The prefix the assistant path matcher requires to resolve the TTS children.
_ASSISTANT_PREFIX = ('main', 'settings', 'Assistant')
_ASSISTANT_TTS_PATH = ('main', 'settings', 'Assistant', 'assistant:tts')


def _run_deep_link(nav: ReducerRunner) -> None:
    for action in _DEEP_LINK_ACTIONS:
        nav.dispatch(action)


class TestTtsSetupDeepLink:
    """The deep-link rebuilds the canonical Assistant TTS navigation path."""

    def test_from_root_lands_on_assistant_tts(self, nav: ReducerRunner) -> None:
        """The sequence lands on the Assistant TTS page from a fresh root."""
        _run_deep_link(nav)
        assert nav.state.path == _ASSISTANT_TTS_PATH

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
        # Simulate the user standing inside the Screen Reader menu.
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushMenuAction(menu_key='settings'))
        nav.dispatch(StackPushMenuAction(menu_key='Accessibility'))
        nav.dispatch(
            StackPushMenuAction(menu_key='speech-synthesis:screen-reader'),
        )
        assert nav.state.path[:3] != _ASSISTANT_PREFIX

        _run_deep_link(nav)

        # Pop-to-root cleared the Accessibility frames; no leftover prefix.
        assert nav.state.path == _ASSISTANT_TTS_PATH
