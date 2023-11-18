# ruff: noqa: D100, D101, D102, D103, D104, D107

from kivy.clock import Clock

from ubo_app.load_services import load_services
from ubo_app.menu import MenuApp
from ubo_app.store import dispatch
from ubo_app.store.status_icons import (
    IconRegistrationAction,
    IconRegistrationActionPayload,
)


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

    load_services()

    app.run()


if __name__ == '__main__':
    main()
