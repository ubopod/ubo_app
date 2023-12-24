# ruff: noqa: D100, D101, D102, D103, D104, D107
import os
import sys

from headless_kivy_pi import HeadlessWidget
from kivy.clock import Clock
from redux import FinishAction

from ubo_app.load_services import load_services
from ubo_app.logging import add_file_handler, add_stdout_handler
from ubo_app.setup_service import setup_service
from ubo_app.store import dispatch


def main() -> None:
    """Instantiate the `MenuApp` and run it."""
    add_file_handler()
    add_stdout_handler()

    if len(sys.argv) > 1 and sys.argv[1] == 'install_service':
        setup_service()
        sys.exit(0)

    os.environ['KIVY_METRICS_DENSITY'] = '1'
    os.environ['KIVY_NO_CONFIG'] = '1'
    os.environ['KIVY_NO_FILELOG'] = '1'
    HeadlessWidget.setup_headless({'automatic_fps': True})

    from ubo_app.menu import MenuApp

    app = MenuApp()

    load_services()

    try:
        app.run()
    finally:
        dispatch(FinishAction())

        # Needed since redux is scheduled using Clock scheduler and Clock doesn't run
        # after app is stopped.
        Clock.tick()


if __name__ == '__main__':
    main()
