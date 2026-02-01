"""gRPC client wrapper for TUI-specific operations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_bindings.ubo.v1 import StatusBarData, ViewData


class TUIClient:
    """Client for TUI to communicate with ubo_app via gRPC."""

    def __init__(self, host: str = "localhost", port: int = 50051) -> None:
        self.host = host
        self.port = port
        self._client = None
        self._unsubscribe_view: Callable[[], None] | None = None

    def connect(self) -> None:
        """Establish gRPC connection."""
        from ubo_bindings.client import UboRPCClient

        self._client = UboRPCClient(self.host, self.port)

    def disconnect(self) -> None:
        """Close gRPC connection."""
        if self._unsubscribe_view:
            self._unsubscribe_view()
        if self._client:
            self._client.close()

    def subscribe_view_changes(
        self,
        callback: Callable[[ViewData, StatusBarData | None], None],
    ) -> Callable[[], None]:
        """Subscribe to view and status bar state changes using autorun.

        This uses autorun to get immediate initial state and updates on changes,
        instead of subscribe_event which only fires on new events.
        """
        if not self._client:
            msg = "Client not connected"
            raise RuntimeError(msg)

        # Use autorun to subscribe to state changes
        # This gives us the initial state immediately plus updates
        @self._client.autorun(
            [
                "state.main.current_view",
                "state.main.status_bar",
            ],
        )
        def handler(results: list) -> None:
            logger.info("autorun handler called with %d results", len(results))
            current_view = results[0] if len(results) > 0 else None
            status_bar = results[1] if len(results) > 1 else None
            logger.info(
                "current_view=%s, status_bar=%s",
                type(current_view).__name__ if current_view else None,
                type(status_bar).__name__ if status_bar else None,
            )
            if current_view is not None:
                callback(current_view, status_bar)
            else:
                logger.warning("current_view is None, skipping callback")

        self._unsubscribe_view = handler
        return handler

    def select_item(self, index: int) -> None:
        """Select menu item by index (0-2 for visible items)."""
        from ubo_bindings.ubo.v1 import Action, MenuChooseByIndexAction

        if self._client:
            action = Action(
                menu_choose_by_index_action=MenuChooseByIndexAction(index=index),
            )
            self._client.dispatch(action=action)

    def select_by_label(self, label: str) -> None:
        """Select menu item by label."""
        from ubo_bindings.ubo.v1 import Action, MenuChooseByLabelAction

        logger.info("select_by_label: dispatching label=%r", label)
        if self._client:
            action = Action(
                menu_choose_by_label_action=MenuChooseByLabelAction(label=label),
            )
            self._client.dispatch(action=action)
            logger.info("select_by_label: dispatch completed")

    def scroll(self, direction: str) -> None:
        """Scroll menu up or down."""
        from ubo_bindings.ubo.v1 import Action, MenuScrollAction, MenuScrollDirection

        if self._client:
            dir_enum = (
                MenuScrollDirection.UP
                if direction == "up"
                else MenuScrollDirection.DOWN
            )
            action = Action(
                menu_scroll_action=MenuScrollAction(direction=dir_enum),
            )
            self._client.dispatch(action=action)

    def go_back(self) -> None:
        """Navigate back in menu hierarchy."""
        from ubo_bindings.ubo.v1 import Action, MenuGoBackAction

        if self._client:
            action = Action(menu_go_back_action=MenuGoBackAction())
            self._client.dispatch(action=action)

    def go_home(self) -> None:
        """Return to home screen."""
        from ubo_bindings.ubo.v1 import Action, MenuGoHomeAction

        if self._client:
            action = Action(menu_go_home_action=MenuGoHomeAction())
            self._client.dispatch(action=action)

    def change_volume(self, amount: float) -> None:
        """Change playback volume by amount (-1.0 to 1.0)."""
        from ubo_bindings.ubo.v1 import Action, AudioChangeVolumeAction, AudioDevice

        if self._client:
            action = Action(
                audio_change_volume_action=AudioChangeVolumeAction(
                    amount=amount,
                    device=AudioDevice.OUTPUT,
                ),
            )
            self._client.dispatch(action=action)

    def execute_action(self, action_id: str) -> None:
        """Execute a menu action by its action_id.

        This dispatches ExecuteMenuActionAction with the given action_id.

        Args:
            action_id: The action_id to execute.
        """
        from ubo_bindings.ubo.v1 import Action, ExecuteMenuActionAction

        if not self._client:
            return

        logger.info("execute_action: dispatching action_id=%s", action_id)
        action = Action(
            execute_menu_action_action=ExecuteMenuActionAction(
                action_id=action_id,
            ),
        )
        self._client.dispatch(action=action)
