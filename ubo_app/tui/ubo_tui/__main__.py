"""Entry point for ubo-tui command."""

from __future__ import annotations

import argparse


def main() -> None:
    """Run the TUI application."""
    parser = argparse.ArgumentParser(description="Ubo TUI Client")
    parser.add_argument(
        "--host",
        default="localhost",
        help="gRPC server host (default: localhost)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=50051,
        help="gRPC server port (default: 50051)",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=4321,
        help=(
            "WebUI HTTP port for file downloads "
            "(default: 4321, matches UBO_WEB_UI_LISTEN_PORT)"
        ),
    )
    args = parser.parse_args()

    from ubo_tui.app import UboTUI

    app = UboTUI(host=args.host, port=args.port, web_port=args.web_port)
    app.run()


if __name__ == "__main__":
    main()
