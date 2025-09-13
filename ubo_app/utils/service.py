"""Ubo service utilities."""

from __future__ import annotations

import sys
import threading
import traceback
from typing import TYPE_CHECKING

from ubo_app.utils.thread import UboThread

if TYPE_CHECKING:
    from ubo_app.service_thread import UboServiceThread
    from ubo_app.utils.types import CoroutineRunner


class ServiceUnavailableError(Exception):
    """Raised when the current service can't be determined."""


def get_service() -> UboServiceThread:
    """Get the current service instance."""
    if 'ubo_app.service_thread' in sys.modules:
        from ubo_app.service_thread import SERVICES_BY_PATH, UboServiceThread

        thread = threading.current_thread()

        if isinstance(thread, UboServiceThread):
            return thread

        if isinstance(thread, UboThread) and thread.ubo_service:
            return thread.ubo_service

        stack = traceback.extract_stack()
        services_by_path = SERVICES_BY_PATH.copy()

        # Optimize by checking stack frames in reverse order and breaking early
        for frame in stack[-2::-1]:
            frame_path = frame.filename
            for registered_path in services_by_path:
                if frame_path.startswith(registered_path.as_posix()):
                    if registered_path in SERVICES_BY_PATH:
                        return SERVICES_BY_PATH[registered_path]
                    break  # Move to next frame if path not found in current services

    msg = 'Service is not available.'
    raise ServiceUnavailableError(msg)


def get_coroutine_runner() -> CoroutineRunner:
    """Get the current service's coroutine runner."""
    try:
        return get_service().run_coroutine
    except ServiceUnavailableError:
        from ubo_app.service import run_coroutine

        return run_coroutine
