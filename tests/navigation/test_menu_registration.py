"""Tests for menu registration (RegisterRegularApp/RegisterSettingApp).

Tests app and settings registration through the reducer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from ubo_gui.menu.types import HeadlessMenu, Menu, SubMenuItem, menu_items

from ubo_app.store.core.menu_adapter import find_sub_menu_item
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

    def test_adds_item_to_apps_menu(self, nav: ReducerRunner) -> None:
        """Verify registering a regular app adds it to the Apps menu."""
        menu_item = SubMenuItem(
            key='test', label='Test App', icon='T',
            sub_menu=HeadlessMenu(title='Test', items=[]),
        )
        action = RegisterRegularAppAction(
            menu_item=menu_item,
            service='test-service',
            key='app1',
        )
        new_state = register_regular_app(nav.state, action)

        # Verify the item was added
        root_items = menu_items(new_state.menu)
        main_item = find_sub_menu_item(root_items, 'main')
        main_items = menu_items(cast('Menu', main_item.sub_menu))
        apps_item = find_sub_menu_item(main_items, 'apps')
        apps_items = menu_items(cast('Menu', apps_item.sub_menu))
        keys = [item.key for item in apps_items]
        assert 'test-service:app1' in keys

    def test_priority_ordering(self, nav: ReducerRunner) -> None:
        """Higher priority items appear first."""
        item_low = SubMenuItem(
            key='low', label='Low Priority', icon='L',
            sub_menu=HeadlessMenu(title='Low', items=[]),
        )
        item_high = SubMenuItem(
            key='high', label='High Priority', icon='H',
            sub_menu=HeadlessMenu(title='High', items=[]),
        )
        state = register_regular_app(
            nav.state,
            RegisterRegularAppAction(
                menu_item=item_low, service='svc', key='low', priority=1,
            ),
        )
        state = register_regular_app(
            state,
            RegisterRegularAppAction(
                menu_item=item_high, service='svc', key='high', priority=10,
            ),
        )

        root_items = menu_items(state.menu)
        main_item = find_sub_menu_item(root_items, 'main')
        main_items = menu_items(cast('Menu', main_item.sub_menu))
        apps_item = find_sub_menu_item(main_items, 'apps')
        apps_items = menu_items(cast('Menu', apps_item.sub_menu))
        keys = [item.key for item in apps_items]
        assert keys.index('svc:high') < keys.index('svc:low')

    def test_duplicate_key_raises(self, nav: ReducerRunner) -> None:
        """Verify registering a duplicate app key raises ValueError."""
        item = SubMenuItem(
            key='dup', label='Dup', icon='D',
            sub_menu=HeadlessMenu(title='Dup', items=[]),
        )
        action = RegisterRegularAppAction(
            menu_item=item, service='svc', key='dup',
        )
        state = register_regular_app(nav.state, action)
        with pytest.raises(ValueError, match='already exists'):
            register_regular_app(state, action)

    def test_no_service_returns_unchanged(self, nav: ReducerRunner) -> None:
        """Verify registering with no service returns state unchanged."""
        item = SubMenuItem(
            key='test', label='Test', icon='T',
            sub_menu=HeadlessMenu(title='Test', items=[]),
        )
        action = RegisterRegularAppAction(
            menu_item=item, service=None, key='test',
        )
        result = register_regular_app(nav.state, action)
        assert result is nav.state


class TestDeregisterRegularApp:
    """Tests for removing regular apps from the Apps menu."""

    def test_removes_from_apps_menu(self, nav: ReducerRunner) -> None:
        """Verify deregistering an app removes it from the Apps menu."""
        item = SubMenuItem(
            key='rm', label='Remove Me', icon='R',
            sub_menu=HeadlessMenu(title='Remove', items=[]),
        )
        state = register_regular_app(
            nav.state,
            RegisterRegularAppAction(menu_item=item, service='svc', key='rm'),
        )
        new_state, _events = deregister_regular_app(
            state,
            DeregisterRegularAppAction(service='svc', key='rm'),
        )

        root_items = menu_items(new_state.menu)
        main_item = find_sub_menu_item(root_items, 'main')
        main_items = menu_items(cast('Menu', main_item.sub_menu))
        apps_item = find_sub_menu_item(main_items, 'apps')
        apps_items = menu_items(cast('Menu', apps_item.sub_menu))
        keys = [item.key for item in apps_items]
        assert 'svc:rm' not in keys

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
        """Verify registering a settings app adds it to the correct category."""
        item = SubMenuItem(
            key='wifi-settings', label='Wi-Fi Settings', icon='W',
            sub_menu=HeadlessMenu(title='Wi-Fi', items=[]),
        )
        action = RegisterSettingAppAction(
            menu_item=item,
            service='wifi-service',
            key='settings',
            category=SettingsCategory.NETWORK,
        )
        new_state = register_setting_app(nav.state, action)

        root_items = menu_items(new_state.menu)
        main_item = find_sub_menu_item(root_items, 'main')
        main_items = menu_items(cast('Menu', main_item.sub_menu))
        settings_item = find_sub_menu_item(main_items, 'settings')
        settings_items = menu_items(cast('Menu', settings_item.sub_menu))

        # Find the Network category
        network_item = next(
            item for item in settings_items
            if item.label == SettingsCategory.NETWORK
        )
        assert isinstance(network_item, SubMenuItem)
        category_items = menu_items(cast('Menu', network_item.sub_menu))
        keys = [item.key for item in category_items]
        assert 'wifi-service:settings' in keys
