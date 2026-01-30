"""Main TUI application."""

from __future__ import annotations

import logging
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Container

from ubo_tui.client import TUIClient
from ubo_tui.views.application import ApplicationView
from ubo_tui.views.home import HomeView
from ubo_tui.views.loading import LoadingView
from ubo_tui.views.menu import MenuView
from ubo_tui.views.notification import NotificationView
from ubo_tui.widgets.status_bar import FooterBar, HeaderBar

# Set up logging to file
logging.basicConfig(
    filename="tui_debug.log",
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class UboTUI(App):
    """Ubo Text User Interface Application."""

    TITLE = "Ubo TUI"
    CSS = """
    Screen {
        layout: vertical;
        background: #0f0f1a;
    }

    #view-container {
        width: 100%;
        height: 1fr;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "go_back", "Back"),
        ("backspace", "go_back", "Back"),
        ("up", "scroll_up", "Up"),
        ("down", "scroll_down", "Down"),
        ("enter", "select", "Select"),
        ("h", "go_home", "Home"),
        ("1", "select_1", "Item 1"),
        ("2", "select_2", "Item 2"),
        ("3", "select_3", "Item 3"),
    ]

    def __init__(
        self,
        host: str = "localhost",
        port: int = 50051,
    ) -> None:
        super().__init__()
        self.client = TUIClient(host, port)
        self._current_view: str = "loading"
        self._selected_index: int = 0
        self._is_home: bool = False  # Will be set when actual view arrives
        self._subscription_task: Any = None

    def compose(self) -> ComposeResult:
        """Create application layout with header, view, and footer."""
        yield HeaderBar(id="header")
        with Container(id="view-container"):
            # Start with loading view - will be replaced when server state arrives
            yield LoadingView(id="view")
        yield FooterBar(id="footer")

    async def on_mount(self) -> None:
        """Set up gRPC connection and subscriptions."""
        import asyncio

        logger.info(
            "on_mount called, connecting to %s:%s",
            self.client.host,
            self.client.port,
        )
        try:
            self.client.connect()
            logger.info("Client connected, starting subscription task")
            # Create the subscription task in the current event loop
            self._subscription_task = asyncio.create_task(self._run_subscription())
            self.notify("Connected to Ubo", severity="information")
        except Exception as e:
            logger.exception("Connection failed")
            self.notify(f"Connection failed: {e}", severity="error")

    async def _run_subscription(self) -> None:
        """Run the state subscription as an async task with auto-reconnect."""
        import asyncio

        from ubo_bindings.client import _unpack_from_any
        from ubo_bindings.store.v1 import SubscribeStoreRequest

        logger.info("Subscription task started")

        retry_count = 0
        max_retries = 10
        base_delay = 1.0

        while retry_count < max_retries:
            if not self.client._client:  # noqa: SLF001
                logger.error("Client not connected")
                return

            try:
                request = SubscribeStoreRequest(
                    selectors=["state.main.current_view", "state.main.status_bar"],
                )
                attempt = retry_count + 1
                logger.info("Sending SubscribeStore request (attempt %d)", attempt)

                async for response in self.client._client.store_service.subscribe_store(  # noqa: SLF001
                    request,
                ):
                    # Reset retry count on successful message
                    retry_count = 0
                    logger.info(
                        "Received subscription response with %d results",
                        len(response.results),
                    )
                    if response.results:
                        results = [_unpack_from_any(item) for item in response.results]
                        current_view = results[0] if len(results) > 0 else None
                        status_bar = results[1] if len(results) > 1 else None
                        logger.info(
                            "Got state: view=%s, status=%s",
                            type(current_view).__name__ if current_view else None,
                            type(status_bar).__name__ if status_bar else None,
                        )
                        if current_view is not None:
                            await self._process_view_change(current_view, status_bar)

            except Exception as e:  # noqa: BLE001
                retry_count += 1
                delay = base_delay * (2 ** (retry_count - 1))  # Exponential backoff
                logger.warning(
                    "Subscription error (attempt %d/%d): %s. Reconnecting in %.1fs...",
                    retry_count,
                    max_retries,
                    e,
                    delay,
                )
                self.notify("Connection lost, reconnecting...", severity="warning")
                await asyncio.sleep(delay)

        logger.error("Max retries reached, subscription task stopping")
        self.notify("Connection failed after retries", severity="error")

    async def on_unmount(self) -> None:
        """Clean up gRPC connection."""
        self.client.disconnect()

    async def _process_view_change(self, view_data: Any, status_bar: Any) -> None:
        """Process view change."""
        logger.info("_process_view_change called")
        # The unpacked data is already the specific view type (e.g., HomeViewData),
        # not a ViewData wrapper. Check the class name or 'type' attribute.
        view_type = None
        actual_view = view_data  # The data IS the view, not a wrapper

        # Get the class name to determine view type
        class_name = type(view_data).__name__
        logger.info("View class name: %s", class_name)

        if class_name == "HomeViewData" or getattr(view_data, "type", "") == "home":
            view_type = "home"
            self._is_home = True
            logger.info("Detected HOME view")
        elif class_name == "MenuViewData" or getattr(view_data, "type", "") == "menu":
            view_type = "menu"
            self._is_home = False
            logger.info("Detected MENU view: %s", getattr(actual_view, "title", "?"))
        elif (
            class_name == "ApplicationViewData"
            or getattr(view_data, "type", "") == "application"
        ):
            view_type = "application"
            self._is_home = False
            app_id = getattr(actual_view, "application_id", "?")
            logger.info("Detected APPLICATION view: %s", app_id)
        elif (
            class_name == "NotificationViewData"
            or getattr(view_data, "type", "") == "notification"
        ):
            view_type = "notification"
            self._is_home = False
            logger.info("Detected NOTIFICATION view")
        else:
            logger.warning(
                "Could not determine view type from view_data: class=%s, type=%s",
                class_name,
                getattr(view_data, "type", "N/A"),
            )

        if view_type and actual_view:
            await self._update_view(view_type, actual_view)

        # Update status bar
        try:
            header = self.query_one("#header", HeaderBar)
            footer = self.query_one("#footer", FooterBar)
            header.update_data(status_bar)
            footer.update_data(status_bar)
        except Exception:  # noqa: BLE001
            pass

    async def _update_view(self, view_type: str, view_data: Any) -> None:
        """Replace current view with new one."""
        logger.info("_update_view called: type=%s", view_type)
        try:
            container = self.query_one("#view-container", Container)
            logger.info("Found view-container")

            # Remove old view - must await since remove() is async
            old_view = container.query_one("#view")
            await old_view.remove()
            logger.info("Removed old view")

            # Create new view based on type
            view_classes = {
                "home": HomeView,
                "menu": MenuView,
                "application": ApplicationView,
                "notification": NotificationView,
            }

            view_class = view_classes.get(view_type, HomeView)
            new_view = view_class(view_data, id="view")
            logger.info("Created new view: %s", view_class.__name__)
            await container.mount(new_view)
            logger.info("Mounted new view successfully")

            self._current_view = view_type
            self._selected_index = 0
        except Exception as e:
            logger.exception("View update failed")
            self.notify(f"View update failed: {e}", severity="error")

    # Action handlers
    def action_go_back(self) -> None:
        """Navigate back."""
        logger.info("action_go_back")
        self.client.go_back()

    def action_go_home(self) -> None:
        """Navigate to home."""
        logger.info("action_go_home")
        self.client.go_home()

    def action_scroll_up(self) -> None:
        """Scroll up or decrease volume on home."""
        logger.info("action_scroll_up (is_home=%s)", self._is_home)
        if self._is_home:
            self.client.change_volume(-0.05)  # -5%
        else:
            self.client.scroll("up")

    def action_scroll_down(self) -> None:
        """Scroll down or increase volume on home."""
        logger.info("action_scroll_down (is_home=%s)", self._is_home)
        if self._is_home:
            self.client.change_volume(0.05)  # +5%
        else:
            self.client.scroll("down")

    def action_select(self) -> None:
        """Select current item."""
        logger.info("action_select (index=%d)", self._selected_index)
        self.client.select_item(self._selected_index)

    def action_select_1(self) -> None:
        """Select first item."""
        logger.info("action_select_1")
        self._selected_index = 0
        self.client.select_item(0)

    def action_select_2(self) -> None:
        """Select second item."""
        logger.info("action_select_2")
        self._selected_index = 1
        self.client.select_item(1)

    def action_select_3(self) -> None:
        """Select third item."""
        logger.info("action_select_3")
        self._selected_index = 2
        self.client.select_item(2)
