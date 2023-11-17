# ruff: noqa: D100, D101, D102, D103, D104, D107
import importlib
import importlib.util
import os
import sys
from pathlib import Path

from kivy.clock import Clock

from ubo_app.menu import MenuApp
from ubo_app.store import dispatch
from ubo_app.store.status_icons import (
    IconRegistrationAction,
    IconRegistrationActionPayload,
)

ROOT_PATH = Path(__file__).parent


def main() -> None:
    """Instantiate the `MenuApp` and run it."""
    app = MenuApp()

    Clock.schedule_interval(
        lambda *_: dispatch(
            [
                IconRegistrationAction(
                    type='STATUS_ICONS_REGISTER',
                    payload=IconRegistrationActionPayload(icon='wifi', priority=-1),
                )
                for _ in range(2)
            ],
        ),
        3,
    )

    for services_directory_path in [
        ROOT_PATH.joinpath('services').as_posix(),
        *(
            os.environ.get('UBO_SERVICES_PATH', '').split(':')
            if os.environ.get('UBO_SERVICES_PATH')
            else []
        ),
    ]:
        if Path(services_directory_path).is_dir():
            for service_path in Path(services_directory_path).iterdir():
                name = service_path.name
                spec = importlib.util.spec_from_file_location(
                    name,
                    location=service_path.joinpath('__init__.py').as_posix(),
                )
                if not spec:
                    continue
                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                if spec.loader:
                    spec.loader.exec_module(module)

    app.run()


if __name__ == '__main__':
    main()
