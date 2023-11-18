# ruff: noqa: D100, D101, D102, D103, D104, D107

from ubo_app.load_services import load_services
from ubo_app.menu import MenuApp


def main() -> None:
    """Instantiate the `MenuApp` and run it."""
    app = MenuApp()

    load_services()

    app.run()


if __name__ == '__main__':
    main()
