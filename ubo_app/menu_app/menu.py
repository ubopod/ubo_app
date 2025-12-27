"""Ubo menu application."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kivy.clock import mainthread
from kivy.graphics.context_instructions import Color
from kivy.graphics.vertex_instructions import Rectangle
from kivy.uix.widget import Widget
from redux import AutorunOptions
from typing_extensions import override
from ubo_gui.app import UboApp

from ubo_app.menu_app.menu_central import MenuAppCentral
from ubo_app.menu_app.menu_footer import MenuAppFooter
from ubo_app.menu_app.menu_header import MenuAppHeader
from ubo_app.store.main import store
from ubo_app.store.services.display import DisplayRedrawEvent

if TYPE_CHECKING:
    from ubo_app.utils.types import Subscriptions


class BlankOverlay(Widget):
    """Full-screen black overlay widget for blanked display."""

    def __init__(self: BlankOverlay, **kwargs: object) -> None:
        """Initialize the blank overlay."""
        super().__init__(**kwargs)
        with self.canvas:
            Color(0, 0, 0, 1)  # Black color
            self.rect = Rectangle(size=self.size, pos=self.pos)
        self.bind(size=self._update_rect, pos=self._update_rect)

    def _update_rect(self: BlankOverlay, *_args: object) -> None:
        """Update rectangle size and position."""
        self.rect.size = self.size
        self.rect.pos = self.pos


class MenuApp(MenuAppCentral, MenuAppFooter, MenuAppHeader, UboApp):
    """Menu application."""

    def __init__(self: MenuApp, **kwargs: object) -> None:
        """Initialize the application."""
        super().__init__(**kwargs)
        self.subscriptions: Subscriptions = []
        self.is_stopped = False
        self.blank_overlay: BlankOverlay | None = None
        self.saved_children: list[Widget] = []

    def set_visual_debug_mode(self: MenuApp, visual_debug: bool) -> None:  # noqa: FBT001
        """Set the visual debug mode."""
        self.root.show_update_regions = visual_debug

    @mainthread
    def handle_blank_state(self: MenuApp, is_blanked: bool) -> None:  # noqa: FBT001
        """Show or hide blank overlay based on blanked state."""
        if is_blanked:
            # Save current children and replace with blank overlay
            self.saved_children = list(self.root.children)
            self.root.clear_widgets()
            if self.blank_overlay is None:
                self.blank_overlay = BlankOverlay(size=self.root.size)
            self.root.add_widget(self.blank_overlay)
        elif self.saved_children:
            # Restore saved children
            self.root.clear_widgets()
            for child in reversed(self.saved_children):
                self.root.add_widget(child)
            self.saved_children = []

    def rerender(self: MenuApp) -> None:
        """Re-render the application."""
        self.root.previous_frame = None
        mainthread(self.root.process_frame)()

    @override
    def on_start(self: MenuApp) -> None:
        """Start the application."""
        from ubo_app.side_effects import setup_side_effects

        self.subscriptions = setup_side_effects()

        store.autorun(
            lambda state: state.settings.visual_debug,
            options=AutorunOptions(keep_ref=False),
        )(self.set_visual_debug_mode)

        # Monitor is_blanked state and show/hide overlay
        store.autorun(
            lambda state: (
                state.display.is_blanked if hasattr(state, 'display') else False
            ),
            options=AutorunOptions(keep_ref=False),
        )(self.handle_blank_state)

        store.subscribe_event(DisplayRedrawEvent, self.rerender, keep_ref=False)

    @override
    def stop(self, *largs: object) -> None:
        """Stop the application."""
        super().stop(*largs)
        self.is_stopped = True
        for cleanup in self.subscriptions:
            cleanup()
