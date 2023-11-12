# ruff: noqa: D100, D101, D102, D103, D104, D107
from ubo_app.menu import MenuApp


def main() -> None:
    app = MenuApp()
    app.run()


if __name__ == '__main__':
    main()
