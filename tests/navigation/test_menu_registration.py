"""Tests for menu registration (RegisterRegularApp/RegisterSettingApp).

Tests app and settings registration through the reducer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ubo_app.store.core.menu_registration import (
    deregister_regular_app,
    register_regular_app,
    register_setting_app,
)
from ubo_app.store.core.types import (
    DeregisterRegularAppAction,
    RegisterRegularAppAction,
    RegisterSettingAppAction,
    SettingsCategory,
)

if TYPE_CHECKING:
    from tests.navigation.conftest import ReducerRunner


class TestRegisterRegularApp:
    """Tests for registering regular apps in the Apps menu."""

    def test_adds_item_to_registered_apps(self, nav: ReducerRunner) -> None:
        """Verify registering a regular app adds it to registered_apps."""
        action = RegisterRegularAppAction(
            label='Test App',
            icon='T',
            service='test-service',
            key='app1',
        )
        new_state = register_regular_app(nav.state, action)

        # Verify the item was added to registered_apps dict
        assert 'test-service:app1' in new_state.registered_apps
        entry = new_state.registered_apps['test-service:app1']
        assert entry.label == 'Test App'
        assert entry.icon == 'T'
        assert entry.category is None  # Regular app, not settings

    def test_priority_ordering(self, nav: ReducerRunner) -> None:
        """Higher priority items are recorded in priorities dict."""
        state = register_regular_app(
            nav.state,
            RegisterRegularAppAction(
                label='Low Priority',
                icon='L',
                service='svc',
                key='low',
                priority=1,
            ),
        )
        state = register_regular_app(
            state,
            RegisterRegularAppAction(
                label='High Priority',
                icon='H',
                service='svc',
                key='high',
                priority=10,
            ),
        )

        # Both should be in registered_apps
        assert 'svc:low' in state.registered_apps
        assert 'svc:high' in state.registered_apps

        # Priorities should be recorded
        assert state.apps_items_priorities.get('svc:high', 0) > \
            state.apps_items_priorities.get('svc:low', 0)

    def test_duplicate_key_raises(self, nav: ReducerRunner) -> None:
        """Verify registering a duplicate app key raises ValueError."""
        action = RegisterRegularAppAction(
            label='Dup',
            icon='D',
            service='svc',
            key='dup',
        )
        state = register_regular_app(nav.state, action)
        with pytest.raises(ValueError, match='already exists'):
            register_regular_app(state, action)

    def test_no_service_returns_unchanged(self, nav: ReducerRunner) -> None:
        """Verify registering with no service returns state unchanged."""
        action = RegisterRegularAppAction(
            label='Test',
            icon='T',
            service=None,
            key='test',
        )
        result = register_regular_app(nav.state, action)
        assert result is nav.state


class TestDeregisterRegularApp:
    """Tests for removing regular apps from the Apps menu."""

    def test_removes_from_registered_apps(self, nav: ReducerRunner) -> None:
        """Verify deregistering an app removes it from registered_apps."""
        state = register_regular_app(
            nav.state,
            RegisterRegularAppAction(
                label='Remove Me',
                icon='R',
                service='svc',
                key='rm',
            ),
        )
        new_state, _events = deregister_regular_app(
            state,
            DeregisterRegularAppAction(service='svc', key='rm'),
        )

        # Verify removed from registered_apps
        assert 'svc:rm' not in new_state.registered_apps

    def test_no_service_returns_unchanged(self, nav: ReducerRunner) -> None:
        """Verify deregistering with no service returns state unchanged."""
        result, events = deregister_regular_app(
            nav.state,
            DeregisterRegularAppAction(service=None, key='test'),
        )
        assert result is nav.state
        assert events == []


class TestRegisterSettingApp:
    """Tests for registering settings apps."""

    def test_adds_to_correct_category(self, nav: ReducerRunner) -> None:
        """Verify registering a settings app adds it to registered_apps."""
        action = RegisterSettingAppAction(
            label='Wi-Fi Settings',
            icon='W',
            service='wifi-service',
            key='settings',
            category=SettingsCategory.NETWORK,
        )
        new_state = register_setting_app(nav.state, action)

        # Verify in registered_apps with correct category
        assert 'wifi-service:settings' in new_state.registered_apps
        entry = new_state.registered_apps['wifi-service:settings']
        assert entry.label == 'Wi-Fi Settings'
        assert entry.category == SettingsCategory.NETWORK.value
