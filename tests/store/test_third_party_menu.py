"""Tests for the Third Party settings dynamic menu.

The Arducam camera entries were silently lost when the legacy menu tree was
replaced by dynamic menus (only the audio entry was ported), so these tests pin
the menu's contents and each entry's dispatched action.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from ubo_app.store.core.action_registry import (
    clear_all_actions,
    execute_action,
    get_registered_actions,
)

if TYPE_CHECKING:
    from redux import BaseAction

CAMERA_ACTION_IDS = (
    'settings:third_party:camera_imx519_af',
    'settings:third_party:camera_imx519_ff',
    'settings:third_party:camera_default',
)


@pytest.fixture
def dispatched(monkeypatch: pytest.MonkeyPatch) -> list[BaseAction]:
    """Capture actions dispatched by the menu setup and its handlers."""
    from ubo_app.store.main import store

    recorded: list[BaseAction] = []
    monkeypatch.setattr(store, 'dispatch', lambda *actions: recorded.extend(actions))
    return recorded


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    """Clear the action registry so registrations don't collide across tests."""
    clear_all_actions()


def _setup(monkeypatch: pytest.MonkeyPatch, *, is_rpi: bool) -> None:
    """Run the Third Party menu setup with eeprom and platform stubbed out."""
    import ubo_app.utils
    import ubo_app.utils.eeprom

    monkeypatch.setattr(ubo_app.utils, 'IS_RPI', is_rpi)
    # No wm8960 speakers, so the audio entry stays out of the way.
    monkeypatch.setattr(
        ubo_app.utils.eeprom,
        'get_eeprom_data',
        lambda: {'speakers': None},
    )

    from ubo_app.store.settings.dynamic_system_menus import (
        _setup_third_party_settings,
    )

    _setup_third_party_settings()


def _menu_items(dispatched: list[Any]) -> tuple[Any, ...]:
    """Pull the items out of the UpdateDynamicMenuAction the setup dispatched."""
    from ubo_app.store.core.types import UpdateDynamicMenuAction
    from ubo_app.store.settings.dynamic_system_menus import THIRD_PARTY_MENU_ID

    action = next(
        action
        for action in dispatched
        if isinstance(action, UpdateDynamicMenuAction)
        and action.menu_id == THIRD_PARTY_MENU_ID
    )
    return tuple(action.items)


def test_camera_entries_present_on_rpi(
    monkeypatch: pytest.MonkeyPatch,
    dispatched: list[Any],
) -> None:
    """The three camera driver entries appear and register their handlers."""
    _setup(monkeypatch, is_rpi=True)

    labels = [item.label for item in _menu_items(dispatched)]
    assert labels == ['Arducam IMX519 AF', 'Arducam IMX519 FF', 'Default Camera']

    registered = get_registered_actions()
    for action_id in CAMERA_ACTION_IDS:
        assert action_id in registered


def test_camera_entries_absent_off_rpi(
    monkeypatch: pytest.MonkeyPatch,
    dispatched: list[Any],
) -> None:
    """Off-device the camera entries are skipped — the overlays are Pi-only."""
    _setup(monkeypatch, is_rpi=False)

    assert _menu_items(dispatched) == ()
    assert not [a for a in get_registered_actions() if a in CAMERA_ACTION_IDS]


@pytest.mark.parametrize(
    ('action_id', 'expected_variant'),
    [
        ('settings:third_party:camera_imx519_af', 'autofocus'),
        ('settings:third_party:camera_imx519_ff', 'fixed-focus'),
    ],
)
def test_install_entry_dispatches_its_own_variant(
    monkeypatch: pytest.MonkeyPatch,
    dispatched: list[Any],
    action_id: str,
    expected_variant: str,
) -> None:
    """Each install entry carries its own overlay variant, not a shared one.

    Guards the closure-capture bug a `for` loop over handlers invites, where
    every entry ends up dispatching the last variant.
    """
    from ubo_app.store.services.camera import CameraInstallDriverAction

    _setup(monkeypatch, is_rpi=True)
    dispatched.clear()

    execute_action(action_id)

    action = next(
        a for a in dispatched if isinstance(a, CameraInstallDriverAction)
    )
    assert (action.make, action.model) == ('arducam', 'imx519')
    assert action.variant == expected_variant


def test_default_camera_entry_dispatches_restore(
    monkeypatch: pytest.MonkeyPatch,
    dispatched: list[Any],
) -> None:
    """The 'Default Camera' entry restores the stock overlay configuration."""
    from ubo_app.store.services.camera import CameraRestoreDefaultAction

    _setup(monkeypatch, is_rpi=True)
    dispatched.clear()

    execute_action('settings:third_party:camera_default')

    assert any(isinstance(a, CameraRestoreDefaultAction) for a in dispatched)
