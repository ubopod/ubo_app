"""Entry point for ubo-gui-client command."""

from __future__ import annotations

import argparse
import os


def _setup_logging(*, verbose: bool = False) -> None:
    """Configure Python logging for the GUI client.

    Always logs to stderr at INFO level (or DEBUG if verbose).
    This is independent of Kivy's console logging.
    """
    import logging
    import sys

    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%H:%M:%S',
        ),
    )

    # Configure all ubo_gui_client loggers
    root_logger = logging.getLogger('ubo_gui_client')
    root_logger.setLevel(level)
    root_logger.addHandler(handler)


def main() -> None:
    """Run the GUI client application."""
    # Must be set before any Kivy import to prevent Kivy from consuming our args
    os.environ['KIVY_NO_ARGS'] = '1'
    os.environ['KIVY_NO_CONFIG'] = '1'
    os.environ['KIVY_NO_FILELOG'] = '1'
    os.environ['KIVY_NO_CONSOLELOG'] = '1'
    os.environ['KCFG_KIVY_EXIT_ON_ESCAPE'] = '0'
    os.environ['KCFG_GRAPHICS_FBO'] = 'force-hardware'
    os.environ['KCFG_GRAPHICS_MULTISAMPLES'] = '0'
    os.environ['KCFG_GRAPHICS_VSYNC'] = '0'

    parser = argparse.ArgumentParser(description='Ubo GUI Client')
    parser.add_argument(
        '--host',
        default='localhost',
        help='gRPC server host (default: localhost)',
    )
    parser.add_argument(
        '--port',
        type=int,
        default=50051,
        help='gRPC server port (default: 50051)',
    )
    parser.add_argument(
        '-v',
        '--verbose',
        action='store_true',
        default=False,
        help='Enable verbose (DEBUG) logging',
    )
    args = parser.parse_args()

    _setup_logging(verbose=args.verbose)

    # Install global exception hooks so crashes are never silent
    import logging
    import sys
    import threading

    _main_logger = logging.getLogger('ubo_gui_client')

    def _excepthook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        _exc_tb: object,
    ) -> None:
        _main_logger.critical(
            'Unhandled exception: %s: %s',
            exc_type.__name__,
            exc_value,
            exc_info=True,
        )

    def _threading_excepthook(hook_args: threading.ExceptHookArgs) -> None:
        _main_logger.critical(
            'Unhandled exception in thread %s: %s: %s',
            hook_args.thread,
            hook_args.exc_type.__name__ if hook_args.exc_type else 'Unknown',
            hook_args.exc_value,
            exc_info=True,
        )

    sys.excepthook = _excepthook
    threading.excepthook = _threading_excepthook

    import headless_kivy.config

    from ubo_gui_client.constants import (
        BYTES_PER_PIXEL,
        DISPLAY_BAUDRATE,
        HEIGHT,
        IS_RPI,
        WIDTH,
    )
    from ubo_gui_client.display import render_on_display

    headless_kivy.config.setup_headless_kivy(
        headless_kivy.config.SetupHeadlessConfig(
            bandwidth_limit=(
                DISPLAY_BAUDRATE // BYTES_PER_PIXEL // 8 if IS_RPI else 0
            ),
            bandwidth_limit_window=0.025,
            bandwidth_limit_overhead=1000,
            region_size=60,
            callback=render_on_display,
            flip_vertical=True,
            width=WIDTH,
            height=HEIGHT,
        ),
    )

    import ubo_gui

    ubo_gui.setup()

    import asyncio

    from ubo_gui_client.app import UboGUIApp

    app = UboGUIApp(host=args.host, port=args.port)
    asyncio.run(app.async_run(async_lib='asyncio'))


if __name__ == '__main__':
    main()
