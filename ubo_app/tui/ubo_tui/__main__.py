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
    args = parser.parse_args()

    from ubo_tui.app import UboTUI

    app = UboTUI(host=args.host, port=args.port)
    app.run()


if __name__ == "__main__":
    main()
