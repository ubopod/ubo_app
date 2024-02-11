# ruff: noqa: D100, D101, D102, D103, D104, D107
import os
import sys
import threading
import traceback
from types import TracebackType

from redux import FinishAction

from ubo_app.constants import GUI_LOG_LEVEL, LOG_LEVEL


def main() -> None:
    """Instantiate the `MenuApp` and run it."""
    if LOG_LEVEL:
        import logging

        from ubo_app.logging import add_file_handler, add_stdout_handler, logger

        logger.setLevel(getattr(logging, LOG_LEVEL))
        add_file_handler(logger, getattr(logging, LOG_LEVEL))
        add_stdout_handler(logger, getattr(logging, LOG_LEVEL))
    if GUI_LOG_LEVEL:
        import logging

        from ubo_gui.logger import add_file_handler as gui_add_file_handler
        from ubo_gui.logger import add_stdout_handler as gui_add_stdout_handler
        from ubo_gui.logger import logger

        logger.setLevel(getattr(logging, GUI_LOG_LEVEL))
        gui_add_file_handler(getattr(logging, GUI_LOG_LEVEL))
        gui_add_stdout_handler(getattr(logging, GUI_LOG_LEVEL))

    if len(sys.argv) > 1 and sys.argv[1] == 'bootstrap':
        from ubo_app.system.bootstrap import bootstrap

        bootstrap(
            with_docker='--with-docker' in sys.argv,
            for_packer='--for-packer' in sys.argv,
        )
        sys.exit(0)

    def global_exception_handler(
        _: type,
        value: Exception,
        tb: TracebackType,
    ) -> None:
        from ubo_app.logging import logger

        logger.error(f'Uncaught exception: {value}')
        logger.error(''.join(traceback.format_tb(tb)))

    # Set the global exception handler
    sys.excepthook = global_exception_handler

    def thread_exception_handler(args: threading.ExceptHookArgs) -> None:
        import traceback

        from ubo_app.logging import logger

        logger.error(
            f"""Exception in thread {args.thread.name if args.thread else "-"}: {
            args.exc_type} {args.exc_value}""",
        )
        logger.error(''.join(traceback.format_tb(args.exc_traceback)))

    threading.excepthook = thread_exception_handler

    from headless_kivy_pi import HeadlessWidget

    os.environ['KIVY_METRICS_DENSITY'] = '1'
    os.environ['KIVY_NO_CONFIG'] = '1'
    os.environ['KIVY_NO_FILELOG'] = '1'
    HeadlessWidget.setup_headless({'automatic_fps': True})

    from kivy.clock import Clock

    from ubo_app.load_services import load_services
    from ubo_app.menu import MenuApp

    # Needed since redux is scheduled using Clock scheduler and Clock doesn't run before
    # app is running
    Clock.tick()

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
