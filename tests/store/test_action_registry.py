"""Tests for action_registry.py.

Pure unit tests for the global action handler registry.
"""

from __future__ import annotations

import pytest

from ubo_app.store.core.action_registry import (
    clear_all_actions,
    execute_action,
    get_registered_actions,
    register_action,
    unregister_action,
)


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    """Clear the action registry before each test."""
    clear_all_actions()


class TestRegisterAction:
    """Tests for register_action."""

    def test_registers_handler(self) -> None:
        """Verify register_action adds the handler to the registry."""
        register_action('test:action', lambda: None)
        assert 'test:action' in get_registered_actions()

    def test_returns_handler(self) -> None:
        """Verify register_action returns the registered handler."""
        handler = lambda: None  # noqa: E731
        result = register_action('test:action', handler)
        assert result is handler

    def test_duplicate_raises_value_error(self) -> None:
        """Verify duplicate registration raises ValueError."""
        register_action('test:action', lambda: None)
        with pytest.raises(ValueError, match='already registered'):
            register_action('test:action', lambda: None)

    def test_allow_reregister_replaces_handler(self) -> None:
        """``allow_reregister=True`` silently replaces an existing handler.

        Services whose setup can run more than once (e.g. a service
        restart) must pass this so re-registration doesn't crash the setup
        path — see the ``ssh:open_menu`` regression (Sentry UBO-APP-PN).
        """
        register_action('test:action', lambda: 'first')
        register_action('test:action', lambda: 'second', allow_reregister=True)
        assert execute_action('test:action') == 'second'


class TestUnregisterAction:
    """Tests for unregister_action."""

    def test_unregisters_existing(self) -> None:
        """Verify unregister_action removes a registered handler."""
        register_action('test:action', lambda: None)
        result = unregister_action('test:action')
        assert result is True
        assert 'test:action' not in get_registered_actions()

    def test_unregister_nonexistent_returns_false(self) -> None:
        """Verify unregistering a nonexistent action returns False."""
        result = unregister_action('nonexistent')
        assert result is False


class TestExecuteAction:
    """Tests for execute_action."""

    def test_executes_handler(self) -> None:
        """Verify execute_action calls the registered handler."""
        called = []
        register_action('test:action', lambda: called.append(True))
        execute_action('test:action')
        assert called == [True]

    def test_executes_handler_returns_value(self) -> None:
        """Verify execute_action returns the handler's return value."""
        register_action('test:return', lambda: 'menu_result')
        result = execute_action('test:return')
        assert result == 'menu_result'

    def test_returns_none_for_missing(self) -> None:
        """Verify execute_action returns None for missing action."""
        result = execute_action('nonexistent')
        assert result is None

    def test_returns_none_on_handler_error(self) -> None:
        """Verify execute_action returns None when handler raises."""
        def failing_handler() -> None:
            msg = 'intentional'
            raise RuntimeError(msg)

        register_action('test:fail', failing_handler)
        result = execute_action('test:fail')
        assert result is None


class TestGetRegisteredActions:
    """Tests for get_registered_actions."""

    def test_empty_initially(self) -> None:
        """Verify registry is empty after clearing."""
        assert get_registered_actions() == []

    def test_lists_registered(self) -> None:
        """Verify get_registered_actions lists all registered ids."""
        register_action('a', lambda: None)
        register_action('b', lambda: None)
        actions = get_registered_actions()
        assert 'a' in actions
        assert 'b' in actions


class TestClearAllActions:
    """Tests for clear_all_actions."""

    def test_clears_all(self) -> None:
        """Verify clear_all_actions removes all registered actions."""
        register_action('a', lambda: None)
        register_action('b', lambda: None)
        clear_all_actions()
        assert get_registered_actions() == []

    def test_clear_empty_is_noop(self) -> None:
        """Verify clearing an empty registry is a safe no-op."""
        clear_all_actions()
        assert get_registered_actions() == []


class TestActionLifecycle:
    """Tests for full register/execute/unregister lifecycle."""

    def test_register_execute_unregister(self) -> None:
        """Verify full register, execute, and unregister lifecycle."""
        results = []
        register_action('lifecycle', lambda: results.append('executed'))
        execute_action('lifecycle')
        assert results == ['executed']
        unregister_action('lifecycle')
        assert execute_action('lifecycle') is None
        assert results == ['executed']  # Not called again

    def test_re_register_after_unregister(self) -> None:
        """Verify re-registration works after unregistering."""
        register_action('reuse', lambda: None)
        unregister_action('reuse')
        # Should not raise
        register_action('reuse', lambda: None)
        assert 'reuse' in get_registered_actions()
