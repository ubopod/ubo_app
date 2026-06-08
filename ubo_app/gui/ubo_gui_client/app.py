"""Main GUI application - uses gRPC exclusively for communication with core."""

from __future__ import annotations

import logging
import math
import time
from typing import TYPE_CHECKING

from kivy.clock import Clock, mainthread
from kivy.graphics.context_instructions import Color
from kivy.graphics.vertex_instructions import Rectangle
from kivy.metrics import dp
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.widget import Widget
from ubo_gui.app import UboApp

from ubo_gui_client.client import GUIClient
from ubo_gui_client.menu_central import MenuAppCentral
from ubo_gui_client.menu_footer import MenuAppFooter
from ubo_gui_client.menu_header import MenuAppHeader

if TYPE_CHECKING:
    from ubo_gui_client.splash import AnimatedSplashOverlay

logger = logging.getLogger(__name__)

SPLASH_MIN_DURATION = 6.3  # seconds to keep splash visible after app start


class BlankOverlay(Widget):
    """Full-screen black overlay widget for blanked display."""

    def __init__(self: BlankOverlay, **kwargs: object) -> None:
        """Initialize the blank overlay."""
        super().__init__(**kwargs)
        with self.canvas:
            Color(0, 0, 0, 1)
            self.rect = Rectangle(size=self.size, pos=self.pos)
        self.bind(size=self._update_rect, pos=self._update_rect)

    def _update_rect(self: BlankOverlay, *_args: object) -> None:
        """Update rectangle size and position."""
        self.rect.size = self.size
        self.rect.pos = self.pos


class DisconnectOverlay(FloatLayout):
    """Full-screen opaque overlay shown when the gRPC connection is lost."""

    def __init__(self: DisconnectOverlay, **kwargs: object) -> None:
        """Initialize the disconnect overlay."""
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(0, 0, 0, 1)
            self._bg_rect = Rectangle(size=self.size, pos=self.pos)
        self.bind(size=self._update_bg, pos=self._update_bg)
        self._title_label = Label(
            text='Disconnected',
            font_size=dp(20),
            bold=True,
            color=(1, 0.3, 0.3, 1),
            size_hint=(1, None),
            height=dp(30),
            pos_hint={'center_x': 0.5, 'center_y': 0.55},
            halign='center',
        )
        self._countdown_label = Label(
            text='',
            font_size=dp(14),
            color=(0.7, 0.7, 0.7, 1),
            size_hint=(1, None),
            height=dp(24),
            pos_hint={'center_x': 0.5, 'center_y': 0.42},
            halign='center',
        )
        self.add_widget(self._title_label)
        self.add_widget(self._countdown_label)

        self._countdown_event = None
        self._remaining: float = 0

    def _update_bg(self: DisconnectOverlay, *_args: object) -> None:
        self._bg_rect.size = self.size
        self._bg_rect.pos = self.pos

    def start_countdown(
        self: DisconnectOverlay,
        delay: float,
        attempt: int,
        max_retries: int,
    ) -> None:
        """Start (or restart) the countdown display."""
        self.stop_countdown()
        self._remaining = delay
        self._title_label.text = 'Disconnected'
        self._update_countdown_text(attempt, max_retries)
        self._countdown_event = Clock.schedule_interval(
            lambda _dt: self._tick(attempt, max_retries),
            1.0,
        )

    def _tick(
        self: DisconnectOverlay,
        attempt: int,
        max_retries: int,
    ) -> None:
        self._remaining = max(0, self._remaining - 1)
        self._update_countdown_text(attempt, max_retries)

    def _update_countdown_text(
        self: DisconnectOverlay,
        attempt: int,
        max_retries: int,
    ) -> None:
        secs = math.ceil(self._remaining)
        self._countdown_label.text = (
            f'Reconnecting in {secs}s  ({attempt}/{max_retries})'
        )

    def stop_countdown(self: DisconnectOverlay) -> None:
        """Cancel any running countdown."""
        if self._countdown_event is not None:
            self._countdown_event.cancel()
            self._countdown_event = None


class UboGUIApp(MenuAppCentral, MenuAppFooter, MenuAppHeader, UboApp):
    """GUI application that communicates with core via gRPC."""

    def __init__(
        self: UboGUIApp,
        host: str = 'localhost',
        port: int = 50051,
        **kwargs: object,
    ) -> None:
        """Initialize the application."""
        self.grpc_client = GUIClient(host=host, port=port)
        super().__init__(**kwargs)
        self.is_stopped = False
        self.blank_overlay: BlankOverlay | None = None
        self.loading_overlay: AnimatedSplashOverlay | None = None
        self.disconnect_overlay: DisconnectOverlay | None = None
        self.saved_children: list[Widget] = []
        self._splash_start_time: float = 0.0
        self._hide_requested: bool = False

    @mainthread
    def handle_blank_state(self: UboGUIApp, is_blanked: bool) -> None:  # noqa: FBT001
        """Show or hide blank overlay based on blanked state."""
        if is_blanked:
            self.saved_children = list(self.root.children)
            self.root.clear_widgets()
            if self.blank_overlay is None:
                self.blank_overlay = BlankOverlay(size=self.root.size)
            self.root.add_widget(self.blank_overlay)
        elif self.saved_children:
            self.root.clear_widgets()
            for child in reversed(self.saved_children):
                self.root.add_widget(child)
            self.saved_children = []

    def rerender(self: UboGUIApp) -> None:
        """Re-render the application."""
        self.root.previous_frame = None
        mainthread(self.root.process_frame)()

    @mainthread
    def show_disconnect_overlay(
        self: UboGUIApp,
        delay: float,
        attempt: int,
        max_retries: int,
    ) -> None:
        """Show the disconnect overlay with a countdown."""
        if self.root is None:
            return
        if self.disconnect_overlay is None:
            self.disconnect_overlay = DisconnectOverlay(
                size=self.root.size,
            )
            self.root.bind(size=self._sync_disconnect_overlay_size)
        if self.disconnect_overlay.parent is None:
            self.root.add_widget(self.disconnect_overlay)
        self.disconnect_overlay.start_countdown(delay, attempt, max_retries)

    @mainthread
    def hide_disconnect_overlay(self: UboGUIApp) -> None:
        """Hide the disconnect overlay."""
        if self.disconnect_overlay is not None:
            self.disconnect_overlay.stop_countdown()
            if self.disconnect_overlay.parent is not None:
                self.disconnect_overlay.parent.remove_widget(self.disconnect_overlay)

    def _sync_disconnect_overlay_size(
        self: UboGUIApp,
        _widget: object,
        size: tuple[int, int],
    ) -> None:
        """Keep the disconnect overlay sized to the root widget."""
        if self.disconnect_overlay is not None:
            self.disconnect_overlay.size = size

    def build(self: UboGUIApp) -> Widget | None:
        """Build root widget, hidden until splash overlay covers it."""
        from ubo_gui_client.constants import IS_TEST_ENV

        root = super().build()

        # Hide the root widget so no uninitialized GUI frames leak to the
        # physical display before on_start adds the splash overlay on top.
        # In test mode, skip this since there's no splash overlay.
        if root is not None and not IS_TEST_ENV:
            root.opacity = 0

        return root

    def on_start(self: UboGUIApp) -> None:
        """Start the application and connect to gRPC."""
        from ubo_gui_client.constants import IS_TEST_ENV

        if not IS_TEST_ENV:
            # Show animated splash, then reveal the root widget underneath
            from ubo_gui_client.splash import AnimatedSplashOverlay

            if self.root is not None:
                self.loading_overlay = AnimatedSplashOverlay(size=self.root.size)
                self.root.add_widget(self.loading_overlay)
                self.root.bind(size=self._sync_loading_overlay_size)
                self.root.opacity = 1
                self._splash_start_time = time.monotonic()
        elif self.root is not None:
            self.root.opacity = 1

        logger.info('[App] on_start: connecting to gRPC...')
        self.grpc_client.connect()
        logger.info(
            '[App] Connected to gRPC server at %s:%d',
            self.grpc_client.host,
            self.grpc_client.port,
        )
        # Now that gRPC is connected, set up the view renderer
        self.setup_view_renderer()
        logger.info('[App] View renderer set up')

        # Register GUI-client page widgets
        from ubo_gui_client.pages import register_all_pages

        register_all_pages()
        logger.info('[App] Page widgets registered')

        # Set up keyboard handling
        from ubo_gui_client.keyboard import setup_keyboard

        self._keyboard_cleanup = setup_keyboard(self.grpc_client, self.menu_widget)
        logger.info('[App] Keyboard handling set up')

        # Subscribe to screenshot events from the core
        self._screenshot_unsubscribe = self.grpc_client.subscribe_screenshot_events(
            self._handle_screenshot_event,
        )
        logger.info('[App] Screenshot event subscription set up, app ready')

    @mainthread
    def hide_loading_overlay(self: UboGUIApp) -> None:
        """Fade out and remove the splash overlay after minimum duration."""
        if self.loading_overlay is None or self._hide_requested:
            return
        self._hide_requested = True
        elapsed = time.monotonic() - self._splash_start_time
        remaining = SPLASH_MIN_DURATION - elapsed
        if remaining > 0:
            Clock.schedule_once(
                lambda _dt: self._do_hide_loading_overlay(),
                remaining,
            )
        else:
            self._do_hide_loading_overlay()

    def _do_hide_loading_overlay(self: UboGUIApp) -> None:
        """Actually dismiss the splash overlay."""
        if self.loading_overlay is None:
            return
        overlay = self.loading_overlay
        self.loading_overlay = None
        overlay.dismiss(
            on_complete=lambda: (
                overlay.parent.remove_widget(overlay)
                if overlay.parent is not None
                else None
            ),
        )

    def _sync_loading_overlay_size(
        self: UboGUIApp,
        _widget: object,
        size: tuple[int, int],
    ) -> None:
        """Keep the loading overlay sized to the root widget."""
        if self.loading_overlay is not None:
            self.loading_overlay.size = size

    @mainthread
    def _handle_screenshot_event(self: UboGUIApp) -> None:
        """Capture window screenshot and send back to core via gRPC.

        Decorated with @mainthread so it runs on the Kivy thread instead of
        blocking the async gRPC event loop.  This prevents a deadlock when
        camera frames are streaming at high frequency: the async loop stays
        free to process state updates and camera events while the screenshot
        is captured on the main thread.

        Forces a fresh full render of the *current* widget state, then defers
        the actual grab by a couple of frames.  ``raw_data`` is updated through
        an async pipeline (GL FBO redraw -> ``process_frame`` -> a thread-pool
        ``render`` that writes ``raw_data``), so grabbing it inline can hash a
        frame that is a tick behind (e.g. a just-painted footer/title) or that
        the render thread is concurrently writing (an off-by-one pixel).  Both
        manifest as snapshot hash flakes.
        """
        from headless_kivy import HeadlessWidget

        root = self.root
        if isinstance(root, HeadlessWidget):
            # Defeat the "no pixels changed" early-out and force the GL FBO to
            # redraw with the latest widget state on the next frame.
            root.previous_frame = None
            root.fbo.ask_update()

        # The FBO redraw + render-thread write happen over the next frames, not
        # synchronously, so capture a couple of frames later (see
        # ``_capture_and_send_screenshot`` for the render-thread join).
        fps = root.fps if isinstance(root, HeadlessWidget) else 24
        Clock.schedule_once(self._capture_and_send_screenshot, 2 / fps)

    def _capture_and_send_screenshot(self: UboGUIApp, _dt: float = 0) -> None:
        """Hash + PNG-encode ``raw_data`` and send it back to core via gRPC."""
        import contextlib
        import hashlib
        import io

        import png
        from headless_kivy import HeadlessWidget

        root = self.root
        if isinstance(root, HeadlessWidget):
            # Block until headless_kivy's render thread has finished writing the
            # latest frame into raw_data so the capture is never torn mid-write
            # or a frame behind.  ``render`` only does pixel maths + SPI display
            # transfer, so joining it on the Kivy thread cannot deadlock.
            task = root.last_render_task
            if task is not None:
                with contextlib.suppress(Exception):
                    task.result(timeout=5)

        array = HeadlessWidget.raw_data
        # Hash on raw_data directly to match headless_kivy_pytest's
        # WindowSnapshot.hash (which uses raw_data.tobytes() without
        # transform_data).
        hash_value = hashlib.sha256(array.tobytes()).hexdigest()
        # Write PNG from the untransformed raw_data
        output = io.BytesIO()
        png.Writer(
            alpha=True,
            width=array.shape[0],
            height=array.shape[1],
            greyscale=False,  # pyright: ignore [reportArgumentType]
            bitdepth=8,
        ).write(output, array.reshape(-1, array.shape[0] * 4).tolist())
        png_bytes = output.getvalue()

        from ubo_bindings.ubo.v1 import Action, ScreenshotDataAction

        self.grpc_client.dispatch_raw(
            Action(
                screenshot_data_action=ScreenshotDataAction(
                    data=png_bytes,
                    hash=hash_value,
                ),
            ),
        )

    def stop(self, *largs: object) -> None:
        """Stop the application."""
        logger.info('[App] Stopping...')
        if self.loading_overlay is not None:
            self.loading_overlay.stop_animation()
            self.loading_overlay = None
        super().stop(*largs)
        self.is_stopped = True
        if hasattr(self, '_keyboard_cleanup'):
            for cleanup in self._keyboard_cleanup:
                cleanup()
        if hasattr(self, '_screenshot_unsubscribe'):
            self._screenshot_unsubscribe()
        self.grpc_client.disconnect()
        logger.info('[App] Stopped')
