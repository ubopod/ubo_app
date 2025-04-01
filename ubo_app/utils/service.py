"""Ubo service utilities."""

from __future__ import annotations

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
    import sys
    import threading

    if 'ubo_app.service_thread' in sys.modules:
        from ubo_app.service_thread import SERVICES_BY_PATH, UboServiceThread

        thread = threading.current_thread()

        if isinstance(thread, UboServiceThread):
            return thread

        if isinstance(thread, UboThread) and thread.ubo_service:
            return thread.ubo_service

        stack = traceback.extract_stack()
        matching_path = next(
            (
                registered_path
                for frame in stack[-2::-1]
                for registered_path in SERVICES_BY_PATH.copy()
                if frame.filename.startswith(registered_path.as_posix())
            ),
            None,
        )
        if matching_path in SERVICES_BY_PATH:
            return SERVICES_BY_PATH[matching_path]

    msg = 'Service is not available.'
    raise ServiceUnavailableError(msg)


def get_coroutine_runner() -> CoroutineRunner:
    """Get the current service's coroutine runner."""
    try:
        return get_service().run_coroutine
    except ServiceUnavailableError:
        from ubo_app.service import run_coroutine

        return run_coroutine
