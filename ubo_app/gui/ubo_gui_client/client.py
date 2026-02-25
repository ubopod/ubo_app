"""gRPC client wrapper for GUI-specific operations."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_bindings.ubo.v1 import Action, StatusBarData, ViewData

# Reconnection parameters
MAX_RETRIES = 50
BASE_DELAY = 1.0
MAX_DELAY = 30.0


class GUIClient:
    """Client for GUI to communicate with ubo_app core via gRPC."""

    def __init__(self, host: str = 'localhost', port: int = 50051) -> None:
        """Initialize the GUI client."""
        self.host = host
        self.port = port
        self._client = None
        self._subscription_task: asyncio.Task | None = None
        self._is_disconnecting: bool = False

    def connect(self) -> None:
        """Establish gRPC connection."""
        from ubo_bindings.client import UboRPCClient

        self._client = UboRPCClient(self.host, self.port)

    def reconnect(self) -> None:
        """Close the current channel and create a fresh connection."""
        if self._client:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                logger.debug('Error closing old client during reconnect', exc_info=True)
        self._client = None
        self.connect()
        logger.info(
            'Reconnected to gRPC server at %s:%d',
            self.host,
            self.port,
        )

    def disconnect(self) -> None:
        """Close gRPC connection."""
        self._is_disconnecting = True
        if self._subscription_task and not self._subscription_task.done():
            self._subscription_task.cancel()
        if self._client:
            self._client.close()

    def subscribe_view_changes(  # noqa: C901
        self,
        callback: Callable[[ViewData, StatusBarData | None], None],
        *,
        on_reconnect: Callable[[], None] | None = None,
        on_disconnect: Callable[[float, int, int], None] | None = None,
        on_connected: Callable[[], None] | None = None,
    ) -> None:
        """Subscribe to view and status bar state changes with auto-reconnect.

        The subscription runs as a background async task. On connection loss,
        it automatically reconnects with exponential backoff (like the TUI
        client).

        Args:
            callback: Called with (view_data, status_bar) on each state update.
            on_reconnect: Called after a successful reconnection so the
                ViewRenderer can reset its state.
            on_disconnect: Called with (delay, attempt, max_retries) when the
                connection drops, before the backoff sleep starts.
            on_connected: Called when the subscription receives its first
                message after a reconnection.

        """
        if not self._client:
            msg = 'Client not connected'
            raise RuntimeError(msg)

        async def _subscription_loop() -> None:  # noqa: C901, PLR0912
            from ubo_bindings.client import _unpack_from_any
            from ubo_bindings.store.v1 import SubscribeStoreRequest

            retry_count = 0
            was_disconnected = False

            while retry_count < MAX_RETRIES and not self._is_disconnecting:
                if not self._client:
                    logger.error(
                        '[GUIClient] Client not connected in subscription loop',
                    )
                    return

                try:
                    request = SubscribeStoreRequest(
                        selectors=[
                            'state.main.current_view',
                            'state.main.status_bar',
                        ],
                    )
                    logger.info(
                        '[GUIClient] Starting subscription (attempt %d)',
                        retry_count + 1,
                    )

                    async for response in self._client.store_service.subscribe_store(
                        request,
                    ):
                        # Signal reconnection success on first message
                        if was_disconnected:
                            was_disconnected = False
                            if on_connected:
                                on_connected()

                        # Reset retry count on successful message
                        retry_count = 0
                        if response.results:
                            results = [
                                _unpack_from_any(item) for item in response.results
                            ]
                            current_view = results[0] if len(results) > 0 else None
                            status_bar_data = results[1] if len(results) > 1 else None
                            if current_view is not None:
                                from typing import cast

                                callback(
                                    cast('ViewData', current_view),
                                    cast('StatusBarData | None', status_bar_data),
                                )

                except asyncio.CancelledError:
                    logger.info('[GUIClient] Subscription cancelled')
                    return
                except Exception:  # noqa: BLE001
                    if self._is_disconnecting:
                        return
                    retry_count += 1
                    was_disconnected = True
                    delay = min(BASE_DELAY * (2 ** (retry_count - 1)), MAX_DELAY)
                    logger.warning(
                        '[GUIClient] Connection lost (attempt %d/%d). '
                        'Reconnecting in %.1fs...',
                        retry_count,
                        MAX_RETRIES,
                        delay,
                        exc_info=True,
                    )

                    if on_disconnect:
                        on_disconnect(delay, retry_count, MAX_RETRIES)

                    await asyncio.sleep(delay)

                    # Recreate the gRPC channel for the next attempt
                    try:
                        self.reconnect()
                        if on_reconnect:
                            on_reconnect()
                    except Exception:  # noqa: BLE001
                        logger.warning(
                            '[GUIClient] Reconnect failed, will retry',
                            exc_info=True,
                        )

            if not self._is_disconnecting:
                logger.error(
                    '[GUIClient] Max retries (%d) reached, subscription stopped',
                    MAX_RETRIES,
                )

        self._subscription_task = self._client.event_loop.create_task(
            _subscription_loop(),
        )

    def select_item(self, index: int) -> None:
        """Select menu item by index (0-2 for visible items)."""
        from ubo_bindings.ubo.v1 import Action, MenuChooseByIndexAction

        if self._client:
            logger.info('[GUIClient] select_item: index=%s', index)
            action = Action(
                menu_choose_by_index_action=MenuChooseByIndexAction(index=index),
            )
            self._client.dispatch(action=action)

    def select_by_label(self, label: str) -> None:
        """Select menu item by label."""
        from ubo_bindings.ubo.v1 import Action, MenuChooseByLabelAction

        if self._client:
            logger.info('[GUIClient] select_by_label: label=%s', label)
            action = Action(
                menu_choose_by_label_action=MenuChooseByLabelAction(label=label),
            )
            self._client.dispatch(action=action)

    def scroll(self, direction: str) -> None:
        """Scroll menu up or down."""
        from ubo_bindings.ubo.v1 import Action, MenuScrollAction, MenuScrollDirection

        if self._client:
            logger.info('[GUIClient] scroll: direction=%s', direction)
            dir_enum = (
                MenuScrollDirection.UP
                if direction == 'up'
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
            logger.info('[GUIClient] go_back')
            action = Action(menu_go_back_action=MenuGoBackAction())
            self._client.dispatch(action=action)

    def go_home(self) -> None:
        """Return to home screen."""
        from ubo_bindings.ubo.v1 import Action, MenuGoHomeAction

        if self._client:
            logger.info('[GUIClient] go_home')
            action = Action(menu_go_home_action=MenuGoHomeAction())
            self._client.dispatch(action=action)

    def change_volume(self, amount: float) -> None:
        """Change playback volume by amount (-1.0 to 1.0)."""
        from ubo_bindings.ubo.v1 import Action, AudioChangeVolumeAction, AudioDevice

        if self._client:
            logger.info('[GUIClient] change_volume: amount=%s', amount)
            action = Action(
                audio_change_volume_action=AudioChangeVolumeAction(
                    amount=amount,
                    device=AudioDevice.OUTPUT,
                ),
            )
            self._client.dispatch(action=action)

    def execute_action(
        self,
        action_id: str,
        menu_key: str | None = None,
    ) -> None:
        """Execute a menu action by its action_id."""
        from ubo_bindings.ubo.v1 import Action, ExecuteMenuActionAction

        if not self._client:
            return

        logger.info('[GUIClient] execute_action: action_id=%s', action_id)
        action = Action(
            execute_menu_action_action=ExecuteMenuActionAction(
                action_id=action_id,
                menu_key=menu_key or '',
            ),
        )
        self._client.dispatch(action=action)

    def dispatch_close_application(self, instance_id: str) -> None:
        """Close an application by instance ID."""
        from ubo_bindings.ubo.v1 import Action, CloseApplicationAction

        if self._client:
            logger.info(
                '[GUIClient] dispatch_close_application: instance_id=%s',
                instance_id,
            )
            action = Action(
                close_application_action=CloseApplicationAction(
                    application_instance_id=instance_id,
                ),
            )
            self._client.dispatch(action=action)

    def dispatch_notifications_clear(self, notification_id: str) -> None:
        """Clear a notification by ID."""
        from ubo_bindings.ubo.v1 import Action, NotificationsClearByIdAction

        if self._client:
            logger.info(
                '[GUIClient] dispatch_notifications_clear: notification_id=%s',
                notification_id,
            )
            action = Action(
                notifications_clear_by_id_action=NotificationsClearByIdAction(
                    id=notification_id,
                ),
            )
            self._client.dispatch(action=action)

    def dispatch_speech_read_text(self, text: str) -> None:
        """Request speech synthesis for text."""
        from ubo_bindings.ubo.v1 import (
            Action,
            ReadableInformation,
            SpeechSynthesisReadTextAction,
        )

        if self._client:
            logger.info('[GUIClient] dispatch_speech_read_text: text=%s', text)
            action = Action(
                speech_synthesis_read_text_action=SpeechSynthesisReadTextAction(
                    information=ReadableInformation(text=text),
                ),
            )
            self._client.dispatch(action=action)

    def dispatch_raw(self, action: Action) -> None:
        """Dispatch a raw protobuf Action to the core."""
        if self._client:
            logger.info('[GUIClient] dispatch_raw: action=%s', type(action).__name__)
            self._client.dispatch(action=action)

    def dispatch_wifi_update_request(self, *, reset: bool = False) -> None:
        """Request a WiFi state update from the core."""
        from ubo_bindings.ubo.v1 import Action, WiFiUpdateRequestAction

        if self._client:
            logger.info('[GUIClient] dispatch_wifi_update_request: reset=%s', reset)
            action = Action(
                wi_fi_update_request_action=WiFiUpdateRequestAction(reset=reset),
            )
            self._client.dispatch(action=action)

    def dispatch_set_enclosures_visible(
        self,
        *,
        header: bool,
        footer: bool,
    ) -> None:
        """Set header/footer visibility."""
        from ubo_bindings.ubo.v1 import Action, SetAreEnclosuresVisibleAction

        if self._client:
            logger.info(
                '[GUIClient] dispatch_set_enclosures_visible: header=%s, footer=%s',
                header,
                footer,
            )
            action = Action(
                set_are_enclosures_visible_action=SetAreEnclosuresVisibleAction(
                    is_header_visible=header,
                    is_footer_visible=footer,
                ),
            )
            self._client.dispatch(action=action)
