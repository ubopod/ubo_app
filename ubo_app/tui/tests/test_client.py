"""Tests for TUI client."""

from __future__ import annotations

DEFAULT_PORT = 50051


def test_client_init() -> None:
    """Test client initialization."""
    from ubo_tui.client import TUIClient

    client = TUIClient("localhost", DEFAULT_PORT)
    assert client.host == "localhost"
    assert client.port == DEFAULT_PORT
    assert client._client is None  # noqa: SLF001


def test_client_init_default() -> None:
    """Test client initialization with defaults."""
    from ubo_tui.client import TUIClient

    client = TUIClient()
    assert client.host == "localhost"
    assert client.port == DEFAULT_PORT


def test_client_disconnect_without_connect() -> None:
    """Test disconnect without connect doesn't error."""
    from ubo_tui.client import TUIClient

    client = TUIClient()
    # Should not raise
    client.disconnect()


def test_client_subscribe_raises_without_connect() -> None:
    """Test subscribe raises when not connected."""
    import pytest

    from ubo_tui.client import TUIClient

    client = TUIClient()

    with pytest.raises(RuntimeError, match="Client not connected"):
        client.subscribe_view_changes(lambda _v, _s: None)


def test_client_actions_noop_without_connect() -> None:
    """Test action methods are no-op when not connected."""
    from ubo_tui.client import TUIClient

    client = TUIClient()
    # These should not raise, just be no-ops
    client.select_item(0)
    client.scroll("up")
    client.scroll("down")
    client.go_back()
    client.go_home()
    client.change_volume(0.05)
