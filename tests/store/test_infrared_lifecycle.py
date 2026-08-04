"""Infrared service lifecycle ownership tests."""

from collections.abc import Callable
from pathlib import Path
from unittest.mock import Mock

import pytest

from tests.service_loader import load_service_modules

_SERVICE_DIR = (
    Path(__file__).resolve().parents[2]
    / 'ubo_app'
    / 'services'
    / '090-infrared'
)

(setup,) = load_service_modules(_SERVICE_DIR, 'setup')


def test_init_service_returns_owned_persistence_cleanups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persistence autoruns are released when the service stops."""
    persistence_cleanups = [Mock() for _ in range(3)]
    persistence_cleanup_iterator = iter(persistence_cleanups)

    def fake_autorun(_selector: object) -> Callable[[object], Mock]:
        def decorator(_reaction: object) -> Mock:
            registration = Mock()
            registration.unsubscribe = Mock()
            return registration

        return decorator

    monkeypatch.setattr(
        setup,
        'register_persistent_store',
        lambda *_args, **_kwargs: next(persistence_cleanup_iterator),
    )
    monkeypatch.setattr(setup, '_register_menus_and_actions', Mock())
    monkeypatch.setattr(setup, 'register_mqtt_components', Mock(return_value=Mock()))
    monkeypatch.setattr(setup.store, 'autorun', fake_autorun)
    monkeypatch.setattr(setup.store, 'dispatch', Mock())
    monkeypatch.setattr(setup.store, 'subscribe_event', Mock(return_value=Mock()))

    subscriptions = setup.init_service()

    assert all(cleanup in subscriptions for cleanup in persistence_cleanups)
