# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import os
from pathlib import Path

import dotenv

from ubo_app.error_handlers import setup_error_handling
from ubo_app.setup import setup

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


def main() -> None:
    """Instantiate the `MenuApp` and run it."""
    os.environ['KIVY_NO_CONFIG'] = '1'
    os.environ['KIVY_NO_FILELOG'] = '1'
    os.environ['KIVY_NO_CONSOLELOG'] = '1'
    os.environ['KCFG_KIVY_EXIT_ON_ESCAPE'] = '0'

    setup()
    setup_error_handling()
    setup_logging()

    from ubo_app.utils.loop import setup_event_loop

    setup_event_loop()

    import headless_kivy_pi.config

    headless_kivy_pi.config.setup_headless_kivy({'automatic_fps': True})

    from ubo_app.load_services import load_services
    from ubo_app.menu_app.menu import MenuApp

    load_services()
    app = MenuApp()

    try:
        app.run()
    except Exception:
        from ubo_app.logging import logger

        logger.exception('An error occurred while running the app.')
        from redux import FinishAction

        from ubo_app.store import dispatch

        dispatch(FinishAction())


if __name__ == '__main__':
    main()
