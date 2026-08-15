"""Ubo service utilities."""

from __future__ import annotations

import inspect
import sys
import threading
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

        services_by_path = SERVICES_BY_PATH.copy()

        # Walk the frames directly rather than via `traceback.extract_stack()`.
        # Only the filenames matter here, but `extract_stack` also resolves the
        # *source line* of every frame — which stats and reads the file behind
        # each one through `linecache`. This runs on every action construction,
        # every `create_task` and every `to_thread`, so that turned a stack walk
        # into a burst of file I/O on the hottest path in the app.
        #
        # Starts at the caller (`f_back`) and walks outward, matching the
        # caller-first order the previous `stack[-2::-1]` slice produced.
        frame = inspect.currentframe()
        frame = frame.f_back if frame else None

        while frame is not None:
            frame_path = frame.f_code.co_filename
            for registered_path in services_by_path:
                if frame_path.startswith(registered_path.as_posix()):
                    if registered_path in SERVICES_BY_PATH:
                        return SERVICES_BY_PATH[registered_path]
                    break  # Move to next frame if path not found in current services
            frame = frame.f_back

    msg = 'Service is not available.'
    raise ServiceUnavailableError(msg)


def get_coroutine_runner() -> CoroutineRunner:
    """Get the current service's coroutine runner."""
    try:
        return get_service().run_coroutine
    except ServiceUnavailableError:
        from ubo_app.service import run_coroutine

        return run_coroutine
