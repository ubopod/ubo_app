"""gRPC client for the LVGL GUI: subscribe to view changes, dispatch actions.

Ported from the Kivy client's GUIClient (which is Kivy-free). Trimmed to the
surface the LVGL client needs: subscription + reconnect + raw action dispatch.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_bindings.ubo.v1 import Action, StatusBarData, ViewData

logger = logging.getLogger(__name__)

INITIAL_DELAY = 0.2
INITIAL_FAST_ATTEMPTS = 8
BASE_DELAY = 1.0
MAX_DELAY = 30.0
MAX_RETRIES = 50


class GUIClient:
    """Communicate with the ubo_app core over gRPC."""

    def __init__(self, host: str = 'localhost', port: int = 50051) -> None:
        """Store the gRPC server host/port (no connection yet)."""
        self.host = host
        self.port = port
        self._client = None
        self._subscription_task: asyncio.Task | None = None
        self._is_disconnecting = False
        self._has_ever_connected = False

    def connect(self) -> None:
        """Open the gRPC channel."""
        from ubo_bindings.client import UboRPCClient

        self._client = UboRPCClient(self.host, self.port)

    def reconnect(self) -> None:
        """Close and re-open the gRPC channel."""
        if self._client:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                logger.debug('Error closing old client', exc_info=True)
        self._client = None
        self.connect()

    def disconnect(self) -> None:
        """Stop the subscription and close the channel."""
        self._is_disconnecting = True
        if self._subscription_task and not self._subscription_task.done():
            self._subscription_task.cancel()
        if self._client:
            self._client.close()

    def dispatch_raw(self, action: Action) -> None:
        """Dispatch a protobuf Action. Call from the client's event loop thread."""
        if self._client:
            self._client.dispatch(action=action)

    def subscribe_screenshot_events(self, callback: Callable[[], None]):  # noqa: ANN201
        """Subscribe to the core's ScreenshotEvent. Returns an unsubscribe fn."""
        if not self._client:
            msg = 'Client not connected'
            raise RuntimeError(msg)
        from ubo_bindings.ubo.v1 import Event, ScreenshotEvent

        return self._client.subscribe_event(
            event_type=Event(screenshot_event=ScreenshotEvent()),
            callback=lambda _event: callback(),
        )

    def subscribe_view_changes(  # noqa: C901
        self,
        callback: Callable[[ViewData, StatusBarData | None, bool | None], None],
        *,
        on_reconnect: Callable[[], None] | None = None,
        on_disconnect: Callable[[float, int, int], None] | None = None,
        on_connected: Callable[[], None] | None = None,
    ) -> None:
        """Subscribe to view / status-bar / blank-state changes with reconnect."""
        if not self._client:
            msg = 'Client not connected'
            raise RuntimeError(msg)

        async def _loop() -> None:  # noqa: C901, PLR0912
            from ubo_bindings.client import _unpack_from_any
            from ubo_bindings.store.v1 import SubscribeStoreRequest

            retry_count = 0
            was_disconnected = False

            while retry_count < MAX_RETRIES and not self._is_disconnecting:
                if not self._client:
                    return
                try:
                    request = SubscribeStoreRequest(
                        selectors=[
                            'state.main.current_view',
                            'state.main.status_bar',
                            'state.display.is_blanked',
                        ],
                    )
                    async for response in self._client.store_service.subscribe_store(
                        request,
                    ):
                        if was_disconnected:
                            was_disconnected = False
                            if on_connected:
                                on_connected()
                        self._has_ever_connected = True
                        retry_count = 0
                        if not response.results:
                            continue
                        results = [_unpack_from_any(i) for i in response.results]
                        current_view = results[0] if len(results) > 0 else None
                        status_bar = results[1] if len(results) > 1 else None
                        blanked_raw = results[2] if len(results) > 2 else None  # noqa: PLR2004
                        is_blanked = (
                            getattr(blanked_raw, 'value', None)
                            if blanked_raw is not None
                            else None
                        )
                        if current_view is not None:
                            callback(
                                cast('ViewData', current_view),
                                cast('StatusBarData | None', status_bar),
                                cast('bool | None', is_blanked),
                            )
                except asyncio.CancelledError:
                    return
                except Exception:  # noqa: BLE001
                    if self._is_disconnecting:
                        return
                    retry_count += 1
                    was_disconnected = True
                    if retry_count <= INITIAL_FAST_ATTEMPTS:
                        delay = INITIAL_DELAY
                    else:
                        n = retry_count - INITIAL_FAST_ATTEMPTS
                        delay = min(BASE_DELAY * (2 ** (n - 1)), MAX_DELAY)
                    logger.warning(
                        'Connection lost (attempt %d/%d), retrying in %.1fs',
                        retry_count,
                        MAX_RETRIES,
                        delay,
                    )
                    if on_disconnect and self._has_ever_connected:
                        on_disconnect(delay, retry_count, MAX_RETRIES)
                    await asyncio.sleep(delay)
                    try:
                        self.reconnect()
                        if on_reconnect:
                            on_reconnect()
                    except Exception:  # noqa: BLE001
                        logger.warning('Reconnect failed, will retry', exc_info=True)

        self._subscription_task = self._client.event_loop.create_task(_loop())
