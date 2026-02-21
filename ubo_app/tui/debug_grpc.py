"""Debug script to test gRPC connection and state subscription."""

from __future__ import annotations

import asyncio
import sys
from typing import Any

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 50051
MIN_ARGC_FOR_PORT = 3


def _print_view_details(current_view: Any) -> None:
    """Print details about the current view."""
    if hasattr(current_view, "home_view_data") and current_view.home_view_data:
        print("  View type: HOME")
        home = current_view.home_view_data
        print(f"  CPU: {home.cpu_percent}%")
        print(f"  RAM: {home.ram_percent}%")
        print(f"  Volume: {home.volume_level}")
    elif hasattr(current_view, "menu_view_data") and current_view.menu_view_data:
        print("  View type: MENU")
        menu = current_view.menu_view_data
        print(f"  Title: {menu.title}")
        print(f"  Items: {len(menu.items)} items")
        for i, item in enumerate(menu.items[:3]):
            print(f"    [{i}] {item.label}")
    elif (
        hasattr(current_view, "application_view_data")
        and current_view.application_view_data
    ):
        print("  View type: APPLICATION")
    elif (
        hasattr(current_view, "notification_view_data")
        and current_view.notification_view_data
    ):
        print("  View type: NOTIFICATION")
    else:
        print(f"  View type: UNKNOWN (fields: {dir(current_view)})")


def _print_state_update(results: list, update_count: int) -> None:
    """Print a state update."""
    current_view = results[0] if len(results) > 0 else None
    status_bar = results[1] if len(results) > 1 else None

    print(f"\n=== State update #{update_count} ===")
    print(f"current_view type: {type(current_view).__name__}")
    print(f"status_bar type: {type(status_bar).__name__}")

    if current_view:
        _print_view_details(current_view)
    else:
        print("  current_view is None!")

    if status_bar:
        print("  Status bar:")
        print(f"    Clock: {getattr(status_bar, 'clock', 'N/A')}")
        print(f"    Temp: {getattr(status_bar, 'temperature', 'N/A')}")


async def test_connection(host: str, port: int) -> None:
    """Test gRPC connection and state subscription using autorun."""
    print(f"Connecting to {host}:{port}...")

    # Import inside function to avoid import errors when not in virtualenv
    from ubo_bindings.client import UboRPCClient  # noqa: PLC0415

    client = UboRPCClient(host, port)
    print(f"Client created, event loop: {client.event_loop}")
    print(f"Current event loop: {asyncio.get_event_loop()}")

    update_count = 0

    def on_state_change(results: list) -> None:
        nonlocal update_count
        update_count += 1
        _print_state_update(results, update_count)

    print("Subscribing to state.main.current_view and state.main.status_bar...")

    @client.autorun(
        [
            "state.main.current_view",
            "state.main.status_bar",
        ],
    )
    def _handler(results: list) -> None:
        on_state_change(results)

    unsubscribe = _handler  # The decorator returns the unsubscribe function

    print("Subscribed! Waiting for state updates (press Ctrl+C to exit)...")
    print("=" * 60)

    try:
        seconds = 0
        while True:
            await asyncio.sleep(1)
            seconds += 1
            if update_count == 0:
                print(f"Waiting... {seconds}s (no updates received yet)", end="\r")
    except KeyboardInterrupt:
        print(f"\n\nReceived {update_count} state updates total")
    finally:
        unsubscribe()
        client.close()
        print("Connection closed")


def main() -> None:
    """Main entry point."""
    host = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_HOST
    port = (
        int(sys.argv[MIN_ARGC_FOR_PORT - 1])
        if len(sys.argv) >= MIN_ARGC_FOR_PORT
        else DEFAULT_PORT
    )

    print(f"Debug gRPC client - connecting to {host}:{port}")
    print("This will subscribe to state.main.current_view and print updates.")
    print("You should see the initial state immediately, then updates on changes.")
    print()

    asyncio.run(test_connection(host, port))


if __name__ == "__main__":
    main()
