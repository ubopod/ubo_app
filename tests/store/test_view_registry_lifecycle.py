"""Fast lifecycle tests for the dynamic view-dependency registry."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from ubo_app.store.core.view_registry import (
    _registry_container,
    create_settings_path_matcher,
    get_apps_menu_title,
    get_category_icon,
    get_home_view_data,
    get_menu_id_for_path,
    get_registered_dependencies,
    get_registered_status_bar_dependencies,
    register_apps_menu_title,
    register_category_icon,
    register_home_view_data_provider,
    register_menu_content_dependency,
    register_path_menu_matcher,
    register_status_bar_dependency,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ubo_app.store.main import RootState


@pytest.fixture(autouse=True)
def _isolated_registry() -> Iterator[None]:
    """Give every test an empty singleton registry and restore prior state."""
    previous = _registry_container[0]
    _registry_container[0] = None
    try:
        yield
    finally:
        _registry_container[0] = previous


def test_path_matcher_priority_cache_and_unregister() -> None:
    """The highest-priority match wins and unregister invalidates cached order."""
    unregister_low = register_path_menu_matcher(
        'low',
        lambda _path: 'low:menu',
        priority=1,
    )
    unregister_high = register_path_menu_matcher(
        'high',
        lambda _path: 'high:menu',
        priority=10,
    )
    try:
        assert get_menu_id_for_path(('main', 'settings')) == 'high:menu'
        unregister_high()
        assert get_menu_id_for_path(('main', 'settings')) == 'low:menu'
    finally:
        unregister_low()


def test_create_settings_path_matcher_requires_the_settings_slot() -> None:
    """The shared matcher rejects short or differently positioned paths."""
    matcher = create_settings_path_matcher('wifi', 'wifi:menu')

    assert matcher(('main', 'settings', 'Network', 'wifi')) == 'wifi:menu'
    assert matcher(('main', 'settings', 'wifi')) is None
    assert matcher(('main', 'settings', 'wifi', 'Network')) is None


def test_dependency_selectors_isolate_provider_errors() -> None:
    """A broken dependency provider cannot prevent other UI updates."""
    unregister_status_ok = register_status_bar_dependency(
        'status:ok',
        lambda state: cast('Any', state).value,
    )
    unregister_status_broken = register_status_bar_dependency(
        'status:broken',
        lambda state: cast('Any', state).missing,
    )
    unregister_menu_ok = register_menu_content_dependency(
        'menu:ok',
        lambda state: cast('Any', state).value * 2,
    )
    unregister_menu_broken = register_menu_content_dependency(
        'menu:broken',
        lambda _state: {}['missing'],
    )
    try:
        state = cast('RootState', SimpleNamespace(value=3))
        assert get_registered_status_bar_dependencies(state) == (3, None)
        assert get_registered_dependencies(state) == (6, None)
    finally:
        unregister_status_ok()
        unregister_status_broken()
        unregister_menu_ok()
        unregister_menu_broken()


def test_view_metadata_registrations_cleanup_to_defaults() -> None:
    """Home providers, title, and category icons leave no stale UI state."""
    unregister_provider = register_home_view_data_provider(
        'home:cpu',
        lambda _state: ('cpu_percent', 42.0),
    )
    unregister_broken_provider = register_home_view_data_provider(
        'home:broken',
        lambda _state: {}['missing'],
    )
    unregister_title = register_apps_menu_title('Applications')
    unregister_icon = register_category_icon('Network', 'wifi')
    try:
        state = cast('RootState', SimpleNamespace())
        assert get_home_view_data(state) == {'cpu_percent': 42.0}
        assert get_apps_menu_title() == 'Applications'
        assert get_category_icon('Network') == 'wifi'
        assert get_category_icon('Missing', 'default') == 'default'
    finally:
        unregister_provider()
        unregister_broken_provider()
        unregister_title()
        unregister_icon()

    assert get_home_view_data(cast('RootState', SimpleNamespace())) == {}
    assert get_apps_menu_title() == 'Apps'
    assert get_category_icon('Network') == ''
