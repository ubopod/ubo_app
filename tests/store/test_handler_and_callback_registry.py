"""Pure tests for prefix action routing and notification cleanup callbacks."""

from __future__ import annotations

import pytest

from ubo_app.store.core.callback_registry import (
    clear_all_callbacks,
    execute_callback,
    register_auto_callback,
    register_callback,
    unregister_callback,
)
from ubo_app.store.core.handler_registry import HandlerRegistry


@pytest.fixture(autouse=True)
def _clear_callbacks() -> None:
    """Keep callback registrations isolated between tests."""
    clear_all_callbacks()


def test_handler_registry_prefers_exact_then_longest_prefix() -> None:
    """Dynamic action IDs route to the most specific registered handler."""
    registry = HandlerRegistry('test')
    calls: list[tuple[str, str]] = []
    registry.register('service:*', lambda action_id: calls.append(('base', action_id)))
    registry.register(
        'service:detail:*',
        lambda action_id: calls.append(('detail', action_id)),
    )
    registry.register('service:detail:exact', lambda: calls.append(('exact', '')))

    assert registry.execute('service:list') == (True, None)
    assert registry.execute('service:detail:42') == (True, None)
    assert registry.execute('service:detail:exact') == (True, None)
    assert calls == [
        ('base', 'service:list'),
        ('detail', 'service:detail:42'),
        ('exact', ''),
    ]


def test_handler_registry_prefix_unregister_and_auto_registration() -> None:
    """Prefix cleanup removes matches and auto IDs remain executable."""
    registry = HandlerRegistry('test')
    calls: list[str] = []
    registry.register('service:*', lambda action_id: calls.append(action_id))
    auto_id = registry.register_auto(lambda: calls.append('auto'))

    assert 'service:item' in registry
    assert registry.unregister('service:*') is True
    assert 'service:item' not in registry
    assert registry.execute(auto_id) == (True, None)
    assert calls == ['auto']


def test_callback_registration_auto_execution_and_cleanup() -> None:
    """Callbacks execute once registered and disappear after explicit cleanup."""
    calls: list[str] = []
    assert register_callback('fixed', lambda: calls.append('fixed')) == 'fixed'
    auto_id = register_auto_callback(lambda: calls.append('auto'))

    assert execute_callback('fixed') is True
    assert execute_callback(auto_id) is True
    assert unregister_callback(auto_id) is True
    assert execute_callback(auto_id) is False
    assert unregister_callback('missing') is False
    assert calls == ['fixed', 'auto']
