"""Main TUI application."""

from __future__ import annotations

import logging
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Container

from ubo_tui.client import TUIClient
from ubo_tui.views.application import ApplicationView
from ubo_tui.views.download_modal import DownloadModal
from ubo_tui.views.home import HomeView
from ubo_tui.views.input_form import InputForm
from ubo_tui.views.instruction import InstructionView
from ubo_tui.views.loading import LoadingView
from ubo_tui.views.menu import MenuView
from ubo_tui.views.notification import NotificationView
from ubo_tui.views.prompt import PromptView
from ubo_tui.views.render import RenderView
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
        ("up", "move_up", "Up"),
        ("down", "move_down", "Down"),
        ("pageup", "page_up", "PgUp"),
        ("pagedown", "page_down", "PgDn"),
        ("enter", "select", "Select"),
        ("h", "go_home", "Home"),
        ("plus", "volume_up", "Vol+"),
        ("minus", "volume_down", "Vol-"),
    ]

    PAGE_STEP = 5

    def __init__(
        self,
        host: str = "localhost",
        port: int = 50051,
        web_port: int = 4321,
    ) -> None:
        super().__init__()
        self.client = TUIClient(host, port, web_port=web_port)
        self._current_view: str = "loading"
        self._selected_index: int = 0
        self._item_count: int = 0
        self._is_home: bool = False  # Will be set when actual view arrives
        self._subscription_task: Any = None
        self._event_subscription_task: Any = None  # FileDownloadReadyEvent stream
        self._notification_id: str | None = None  # Track current notification
        self._displayed_input_id: str | None = None  # Track open InputForm modal

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
            logger.info("Client connected, starting subscription tasks")
            # Create the subscription tasks in the current event loop.
            self._subscription_task = asyncio.create_task(self._run_subscription())
            self._event_subscription_task = asyncio.create_task(
                self._run_event_subscription(),
            )
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
                    selectors=[
                        "state.main.current_view",
                        "state.main.status_bar",
                        # NOTE: subscribe to state.web_ui (a WebUiState
                        # message) rather than state.web_ui.active_inputs
                        # directly — the gRPC store-subscribe layer rejects
                        # Sequence return types from selectors. We extract
                        # the list locally via _extract_active_inputs.
                        "state.web_ui",
                    ],
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
                        web_ui_state = (
                            results[2] if len(results) > 2 else None  # noqa: PLR2004
                        )
                        logger.info(
                            "Got state: view=%s, status=%s, web_ui=%s",
                            type(current_view).__name__ if current_view else None,
                            type(status_bar).__name__ if status_bar else None,
                            type(web_ui_state).__name__ if web_ui_state else None,
                        )
                        if current_view is not None:
                            await self._process_view_change(current_view, status_bar)
                        # web_ui_state may be the WebUiState message or just
                        # the active_inputs list, depending on how the server
                        # serializes the selector path. Extract defensively.
                        active_inputs = self._extract_active_inputs(web_ui_state)
                        await self._process_input_queue(active_inputs)

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

    async def _run_event_subscription(self) -> None:
        """Stream FileDownloadReadyEvent and push DownloadModal on each."""
        import asyncio

        from ubo_bindings.store.v1 import SubscribeEventRequest
        from ubo_bindings.ubo.v1 import Event, FileDownloadReadyEvent

        retry_count = 0
        max_retries = 10
        base_delay = 1.0

        while retry_count < max_retries:
            if not self.client._client:  # noqa: SLF001
                logger.error("Event subscription: client not connected")
                return

            try:
                request = SubscribeEventRequest(
                    events=[
                        Event(file_download_ready_event=FileDownloadReadyEvent()),
                    ],
                )
                logger.info(
                    "Sending SubscribeEvent request (FileDownloadReadyEvent)",
                )
                async for response in (
                    self.client._client.store_service.subscribe_event(  # noqa: SLF001
                        request,
                    )
                ):
                    retry_count = 0
                    event = response.event
                    download_event = getattr(
                        event,
                        "file_download_ready_event",
                        None,
                    )
                    if download_event is None:
                        continue
                    token = getattr(download_event, "download_token", "") or ""
                    filename = getattr(download_event, "filename", "") or ""
                    if not token:
                        continue
                    logger.info(
                        "FileDownloadReadyEvent: token=%s filename=%r",
                        token,
                        filename,
                    )
                    self._show_download_modal(token, filename)

            except Exception as e:  # noqa: BLE001
                retry_count += 1
                delay = base_delay * (2 ** (retry_count - 1))
                logger.warning(
                    "Event subscription error (attempt %d/%d): %s",
                    retry_count,
                    max_retries,
                    e,
                )
                await asyncio.sleep(delay)

        logger.error("Event subscription: max retries reached, stopping")

    def _show_download_modal(self, token: str, filename: str) -> None:
        """Push the DownloadModal for a ready download."""
        try:
            self.push_screen(DownloadModal(self.client, token, filename))
        except Exception:
            logger.exception("Failed to push DownloadModal")

    async def on_unmount(self) -> None:
        """Clean up gRPC connection."""
        if self._event_subscription_task is not None:
            self._event_subscription_task.cancel()
        self.client.disconnect()

    @staticmethod
    def _extract_active_inputs(web_ui_state: Any) -> list[Any]:
        """Pull the active_inputs list from a WebUiState (or list/None)."""
        if web_ui_state is None:
            return []
        # If the server returns the state object directly, drill into it.
        active = getattr(web_ui_state, "active_inputs", None)
        if active is not None:
            return list(active)
        # Fallback: assume the server returned just the list.
        if isinstance(web_ui_state, list):
            return web_ui_state
        return []

    async def _process_input_queue(self, active_inputs: list[Any]) -> None:
        """Show or dismiss the InputForm modal based on the queue head."""
        head_id = ""
        head: Any = None
        if active_inputs:
            head = active_inputs[0]
            head_id = getattr(head, "id", "") or ""

        if head_id == self._displayed_input_id:
            return

        # The displayed input was resolved (or replaced): pop it.
        if self._displayed_input_id is not None:
            try:
                if isinstance(self.screen, InputForm):
                    self.pop_screen()
            except Exception:
                logger.exception("Failed to pop InputForm")
            self._displayed_input_id = None

        if not head_id or head is None:
            return

        # Push a new InputForm for the new head.
        try:
            self._displayed_input_id = head_id
            self.push_screen(InputForm(head, self.client))
            logger.info("Pushed InputForm for id=%s", head_id)
        except Exception:
            logger.exception("Failed to push InputForm")
            self._displayed_input_id = None

    _VIEW_TYPES = (
        ("HomeViewData", "home"),
        ("MenuViewData", "menu"),
        ("ApplicationViewData", "application"),
        ("RenderViewData", "render"),
        ("PromptViewData", "prompt"),
        ("InstructionViewData", "instruction"),
        ("NotificationViewData", "notification"),
    )

    def _classify_view(self, view_data: Any) -> str | None:
        """Map a server-side view payload to a local view-type string."""
        class_name = type(view_data).__name__
        type_attr = getattr(view_data, "type", "")
        for expected_class, view_type in self._VIEW_TYPES:
            if class_name == expected_class or type_attr == view_type:
                return view_type
        return None

    async def _process_view_change(self, view_data: Any, status_bar: Any) -> None:
        """Process view change."""
        logger.info("_process_view_change called")
        class_name = type(view_data).__name__
        logger.info("View class name: %s", class_name)
        actual_view = view_data
        view_type = self._classify_view(view_data)

        if view_type is None:
            logger.warning(
                "Could not determine view type from view_data: class=%s, type=%s",
                class_name,
                getattr(view_data, "type", "N/A"),
            )
        elif view_type == "notification":
            # Skip empty notifications (race condition where notification is cleared
            # from state but stack still has NotificationStackItem).
            title = getattr(actual_view, "title", "") or ""
            items_container = getattr(actual_view, "items", None)
            has_items = bool(
                items_container and getattr(items_container, "items", None),
            )
            if not title and not has_items:
                notification_id = getattr(actual_view, "notification_id", None)
                logger.info(
                    "Skipping empty notification view: id=%s (no title, no items)",
                    notification_id,
                )
                return
            self._is_home = False
            self._notification_id = getattr(actual_view, "notification_id", None)
            logger.info(
                "Detected NOTIFICATION view: id=%s",
                self._notification_id,
            )
        else:
            self._is_home = view_type == "home"
            logger.info("Detected %s view", view_type.upper())

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
        """Update or replace the current view."""
        cur = self._current_view
        logger.info("_update_view: type=%s (current=%s)", view_type, cur)

        # If same view type, update in place to preserve selection
        if view_type == self._current_view:
            try:
                if view_type == "home":
                    view = self.query_one("#view", HomeView)
                    view.update_data(view_data)
                    logger.info("Updated HomeView data in place")
                    return
                # Menu views with same title can also be updated in place
                # But for now, only optimize home view (most frequent updates)
            except Exception:  # noqa: BLE001
                logger.info("Could not update in place, will replace view")

        # Replace view with new one
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
                "prompt": PromptView,
                "instruction": InstructionView,
                "render": RenderView,
            }

            view_class = view_classes.get(view_type, HomeView)
            new_view = view_class(view_data, id="view")
            logger.info("Created new view: %s", view_class.__name__)
            await container.mount(new_view)
            logger.info("Mounted new view successfully")

            self._current_view = view_type
            self._selected_index = 0

            # Track item count for navigable views (menu/home/notification/prompt)
            is_menu = view_type == "menu" and isinstance(new_view, MenuView)
            is_home = view_type == "home" and isinstance(new_view, HomeView)
            is_notif = view_type == "notification"
            is_notif = is_notif and isinstance(new_view, NotificationView)
            is_prompt = view_type == "prompt" and isinstance(new_view, PromptView)
            has_items = is_menu or is_home or is_notif or is_prompt
            self._item_count = new_view.item_count if has_items else 0
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

    def action_move_up(self) -> None:
        """Move selection up."""
        idx, count = self._selected_index, self._item_count
        logger.info("action_move_up (index=%d, count=%d)", idx, count)
        navigable_views = ("menu", "home", "notification", "prompt")
        if self._current_view in navigable_views and self._selected_index > 0:
            self._selected_index -= 1
            self._update_view_selection()

    def action_move_down(self) -> None:
        """Move selection down."""
        idx, count = self._selected_index, self._item_count
        logger.info("action_move_down (index=%d, count=%d)", idx, count)
        navigable_views = ("menu", "home", "notification", "prompt")
        can_move = (
            self._current_view in navigable_views
            and self._selected_index < self._item_count - 1
        )
        if can_move:
            self._selected_index += 1
            self._update_view_selection()

    def action_page_up(self) -> None:
        """Jump selection up by PAGE_STEP, clamped to 0."""
        navigable_views = ("menu", "home", "notification", "prompt")
        if self._current_view not in navigable_views or self._item_count <= 0:
            return
        new_index = max(0, self._selected_index - self.PAGE_STEP)
        if new_index != self._selected_index:
            self._selected_index = new_index
            self._update_view_selection()

    def action_page_down(self) -> None:
        """Jump selection down by PAGE_STEP, clamped to item_count - 1."""
        navigable_views = ("menu", "home", "notification", "prompt")
        if self._current_view not in navigable_views or self._item_count <= 0:
            return
        new_index = min(
            self._item_count - 1,
            self._selected_index + self.PAGE_STEP,
        )
        if new_index != self._selected_index:
            self._selected_index = new_index
            self._update_view_selection()

    def action_volume_up(self) -> None:
        """Increase volume."""
        logger.info("action_volume_up")
        self.client.change_volume(0.05)

    def action_volume_down(self) -> None:
        """Decrease volume."""
        logger.info("action_volume_down")
        self.client.change_volume(-0.05)

    def _handle_notification_select(self, idx: int) -> bool:
        """Handle item selection in notification views.

        Returns True if handled, False otherwise.
        """
        try:
            view = self.query_one("#view", NotificationView)
            label = view.get_item_label(idx)
            action_id = view.get_item_action_id(idx)
            logger.info(
                "action_select notification: label=%r index=%d action_id=%s",
                label,
                idx,
                action_id,
            )
            if action_id:
                # Handle extra_info action locally - display the text
                # Matches NOTIFICATION_EXTRA_INFO_PREFIX
                # in ubo_app/store/core/constants.py
                if action_id.startswith("notification:extra_info:"):
                    extra_info = view.get_extra_information()
                    if extra_info:
                        self.notify(extra_info, title="Info", timeout=10)
                        logger.info("Displayed extra information: %s", extra_info)
                    else:
                        self.notify("No additional information", timeout=3)
                else:
                    # Dispatch other actions to server
                    self.client.execute_action(action_id)
        except Exception:
            logger.exception("action_select notification: exception")
            return False
        else:
            return True

    def action_select(self) -> None:
        """Select current item."""
        idx = self._selected_index
        logger.info("action_select (index=%d, view=%s)", idx, self._current_view)

        is_notification = self._current_view == "notification"
        if is_notification and self._handle_notification_select(idx):
            return

        if self._current_view == "prompt":
            try:
                view = self.query_one("#view", PromptView)
                label = view.get_item_label(idx)
                if label:
                    logger.info("action_select prompt: select_by_label(%r)", label)
                    self.client.select_by_label(label)
                    return
            except Exception:
                logger.exception("action_select prompt: exception")

        if self._current_view in ("menu", "home"):
            # Select by label (works with any index, not just 0-2)
            try:
                if self._current_view == "menu":
                    view = self.query_one("#view", MenuView)
                else:
                    view = self.query_one("#view", HomeView)
                label = view.get_item_label(idx)
                logger.info("action_select: label=%r for index=%d", label, idx)
                if label:
                    logger.info("action_select: select_by_label(%r)", label)
                    self.client.select_by_label(label)
                    return
            except Exception:
                logger.exception("action_select: exception getting label")
        # Fallback to index-based selection
        logger.info("action_select: fallback select_item(%d)", idx)
        self.client.select_item(idx)

    def _update_view_selection(self) -> None:
        """Update the visual selection in the current view."""
        try:
            if self._current_view == "menu":
                view = self.query_one("#view", MenuView)
                view.update_selection(self._selected_index)
            elif self._current_view == "home":
                view = self.query_one("#view", HomeView)
                view.update_selection(self._selected_index)
            elif self._current_view == "notification":
                view = self.query_one("#view", NotificationView)
                view.update_selection(self._selected_index)
            elif self._current_view == "prompt":
                view = self.query_one("#view", PromptView)
                view.update_selection(self._selected_index)
        except Exception:  # noqa: BLE001
            pass
