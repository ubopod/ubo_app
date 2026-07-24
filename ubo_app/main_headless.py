# ruff: noqa: D100
from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import dotenv

from ubo_app.logger import setup_loggers
from ubo_app.setup_headless import setup_headless
from ubo_app.utils.error_handlers import setup_error_handling

dotenv.load_dotenv(Path(__file__).parent / '.dev.env')
dotenv.load_dotenv(Path(__file__).parent / '.env')

# Headroom above the steady-state fd usage (web server, gRPC, sockets, mics).
_OPEN_FILE_LIMIT_TARGET = 8192


def _raise_open_file_limit() -> None:
    """Raise the soft open-files limit so services don't exhaust the inherited cap.

    The core runs the Web UI server, gRPC, audio and many sockets concurrently; a
    process launched from a context with the default soft limit (e.g. macOS
    launchd's 256) runs only a few fds under the ceiling, and a single restart can
    tip a service over — the Web UI setup then dies with ``OSError(24)`` and input
    forms never render. Raise our own soft limit at startup, capped at the hard
    limit, so launch context no longer decides this.
    """
    import resource

    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    target = _OPEN_FILE_LIMIT_TARGET
    if hard != resource.RLIM_INFINITY and 0 < hard < target:
        target = hard
    if soft < target:
        with contextlib.suppress(ValueError, OSError):
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))


def main() -> None:
    """Start the headless core (no Kivy/GUI dependencies)."""
    _raise_open_file_limit()
    logger_cleanups = setup_loggers()

    setup_error_handling()

    from ubo_app.service_thread import load_services, stop_services

    setup_headless()

    from ubo_app.logger import logger

    logger.info('-------------------Starting the headless core-------------------')

    from ubo_app.constants import DISABLE_GRPC, DISABLE_MCU_SERVER
    from ubo_app.service import worker_thread

    if not DISABLE_GRPC:
        from ubo_app.rpc.server import serve as grpc_serve

        worker_thread.run_coroutine(grpc_serve())

    if not DISABLE_MCU_SERVER:
        from ubo_app.rpc.mcu_server import serve as mcu_serve

        worker_thread.run_coroutine(mcu_serve())

    load_services()

    from ubo_app.side_effects import setup_side_effects

    subscriptions = [*setup_side_effects()]

    from ubo_app.store.core.menu_event_handlers import setup_menu_event_handlers

    subscriptions.extend(setup_menu_event_handlers())

    from redux import FinishEvent

    from ubo_app.store.main import store

    finish_event = asyncio.Event()
    store.subscribe_event(FinishEvent, lambda: finish_event.set())

    try:
        worker_thread.is_finished.wait()
    except KeyboardInterrupt:
        logger.info('Keyboard interrupt received, shutting down...')
        from redux import FinishAction

        store.dispatch(FinishAction())
        worker_thread.is_finished.wait()
    finally:
        from ubo_app.service_thread import SERVICES_BY_PATH

        stop_services()

        for service in list(SERVICES_BY_PATH.values()):
            service.join()

        for cleanup in subscriptions:
            cleanup()

        from ubo_app.setup_headless import clear_signal_handlers

        clear_signal_handlers()
        for cleanup in logger_cleanups:
            cleanup()


if __name__ == '__main__':
    main()
