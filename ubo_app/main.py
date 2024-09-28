# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import dotenv

from ubo_app.error_handlers import setup_error_handling
from ubo_app.logging import setup_logging
from ubo_app.setup import setup

dotenv.load_dotenv(Path(__file__).parent / '.dev.env')
dotenv.load_dotenv(Path(__file__).parent / '.env')


def main() -> None:
    """Instantiate the `MenuApp` and run it."""
    # `setup_logging` imports `ubo_gui` which imports `kivy`, so we need to set these
    # environment variables before calling `setup_logging`
    os.environ['KIVY_NO_CONFIG'] = '1'
    os.environ['KIVY_NO_FILELOG'] = '1'
    os.environ['KIVY_NO_CONSOLELOG'] = '1'
    os.environ['KCFG_KIVY_EXIT_ON_ESCAPE'] = '0'

    # `setup_logging` needs to be called before anything else to initialize the rotating
    # log files
    setup_logging()

    # `setup_error_handling` needs to be called before anything else and after
    # `setup_logging`
    setup_error_handling()

    # This should be imported early to set the custom loader
    from ubo_app.load_services import load_services

    setup()

    from ubo_app.service import start_event_loop_thread, worker_thread

    start_event_loop_thread(asyncio.get_event_loop())

    import headless_kivy.config

    from ubo_app.constants import DISABLE_GRPC, HEIGHT, WIDTH
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

    if not DISABLE_GRPC:
        from ubo_app.rpc.server import serve as grpc_serve

        worker_thread.run_task(grpc_serve())

    load_services()
    app = MenuApp()

    try:
        app.run()
    except Exception:
        logger.exception('An error occurred while running the app.')
        from redux import FinishAction

        from ubo_app.store.main import store

        store.dispatch(FinishAction())


if __name__ == '__main__':
    main()
