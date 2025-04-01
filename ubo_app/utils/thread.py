"""Thread class that tracks the UboService starting it."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ubo_app.service_thread import UboServiceThread


class UboThread(threading.Thread):
    """Thread class that tracks the `UboService` starting it."""

    ubo_service: UboServiceThread | None = None

    def start(self) -> None:
        """Start the thread."""
        from ubo_app.utils.service import get_service

        self.ubo_service = get_service()
        super().start()
