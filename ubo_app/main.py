# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import os
from pathlib import Path

import dotenv

from ubo_app.error_handlers import setup_error_handling
from ubo_app.logging import setup_logging
from ubo_app.setup import setup

dotenv.load_dotenv(Path(__file__).parent / '.dev.env')


def main() -> None:
    """Instantiate the `MenuApp` and run it."""
    # This should be imported early to set the custom loader
    from ubo_app.load_services import load_services

    os.environ['KIVY_NO_CONFIG'] = '1'
    os.environ['KIVY_NO_FILELOG'] = '1'
    os.environ['KIVY_NO_CONSOLELOG'] = '1'
    os.environ['KCFG_KIVY_EXIT_ON_ESCAPE'] = '0'

    setup()
    setup_logging()
    setup_error_handling()

    from ubo_app.service import start_event_loop

    start_event_loop()

    import headless_kivy.config

    from ubo_app.constants import HEIGHT, WIDTH
    from ubo_app.display import render_on_display

    headless_kivy.config.setup_headless_kivy(
        {
            'callback': render_on_display,
            'automatic_fps': True,
            'flip_vertical': True,
            'width': WIDTH,
            'height': HEIGHT,
        },
    )

    from ubo_app.logging import logger
    from ubo_app.menu_app.menu import MenuApp

    logger.info('----------------------Starting the app----------------------')

    load_services()
    app = MenuApp()

    try:
        app.run()
    except Exception:
        logger.exception('An error occurred while running the app.')
        from redux import FinishAction

        from ubo_app.store.main import dispatch

        dispatch(FinishAction())


if __name__ == '__main__':
    main()
