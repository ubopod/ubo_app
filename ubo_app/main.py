# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import os
import sys
import threading
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

import dotenv
import sentry_sdk
from redux import FinishAction

if TYPE_CHECKING:
    from types import TracebackType

dotenv.load_dotenv(Path(__file__).parent / '.dev.env')


def setup_logging() -> None:
    from ubo_app.constants import GUI_LOG_LEVEL, LOG_LEVEL

    if LOG_LEVEL:
        import logging

        import ubo_app.logging

        level = getattr(
            ubo_app.logging,
            LOG_LEVEL,
            getattr(logging, LOG_LEVEL, logging.INFO),
        )

        ubo_app.logging.logger.setLevel(level)
        ubo_app.logging.add_file_handler(ubo_app.logging.logger, level)
        ubo_app.logging.add_stdout_handler(ubo_app.logging.logger, level)
    if GUI_LOG_LEVEL:
        import logging

        import ubo_gui.logger

        level = getattr(
            ubo_gui.logger,
            GUI_LOG_LEVEL,
            getattr(logging, GUI_LOG_LEVEL, logging.INFO),
        )

        ubo_gui.logger.logger.setLevel(level)
        ubo_gui.logger.add_file_handler(level)
        ubo_gui.logger.add_stdout_handler(level)


def setup_sentry() -> None:  # pragma: no cover
    from ubo_app.constants import SENTRY_DSN

    if SENTRY_DSN:
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            traces_sample_rate=1.0,
            profiles_sample_rate=1.0,
        )


def get_all_thread_stacks() -> dict[str, list[str]]:
    id_to_name = {th.ident: th.name for th in threading.enumerate()}
    thread_stacks = {}
    for thread_id, frame in sys._current_frames().items():  # noqa: SLF001
        thread_stacks[id_to_name.get(thread_id, f'unknown-{thread_id}')] = (
            traceback.format_stack(frame)
        )
    return thread_stacks


def global_exception_handler(
    exception_type: type[BaseException],
    exception_value: BaseException,
    exception_traceback: TracebackType,
) -> None:
    from ubo_app.logging import logger

    error_message = ''.join(
        traceback.format_exception(
            exception_type,
            exception_value,
            exception_traceback,
        ),
    )
    threads_info = get_all_thread_stacks()

    logger.error(
        f'Uncaught exception: {exception_type}: {exception_value}\n{error_message}',
    )
    logger.debug(
        f'Uncaught exception: {exception_type}: {exception_value}\n{error_message}',
        extra={'threads': threads_info},
    )


def main() -> None:
    """Instantiate the `MenuApp` and run it."""
    os.environ['KIVY_NO_CONFIG'] = '1'
    os.environ['KIVY_NO_FILELOG'] = '1'
    os.environ['KIVY_NO_CONSOLELOG'] = '1'
    os.environ['KCFG_KIVY_EXIT_ON_ESCAPE'] = '0'

    setup_sentry()
    setup_logging()

    # Set the global exception handler
    sys.excepthook = global_exception_handler
    threading.excepthook = global_exception_handler

    if len(sys.argv) > 1 and sys.argv[1] == 'bootstrap':
        from ubo_app.system.bootstrap import bootstrap

        bootstrap(
            with_docker='--with-docker' in sys.argv,
            for_packer='--for-packer' in sys.argv,
        )
        sys.exit(0)

    import headless_kivy_pi.config

    headless_kivy_pi.config.setup_headless_kivy({'automatic_fps': True})

    from kivy.clock import Clock

    from ubo_app.load_services import load_services
    from ubo_app.menu import MenuApp

    load_services()
    app = MenuApp()

    try:
        app.run()
    finally:
        from ubo_app.store import dispatch

        dispatch(FinishAction())

        # Needed since redux is scheduled using Clock scheduler and Clock doesn't run
        # after app is stopped.
        Clock.tick()


if __name__ == '__main__':
    main()
