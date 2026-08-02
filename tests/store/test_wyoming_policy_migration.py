"""The older single-policy layout maps onto the combinable one.

The first layout stored one ``connection_policy`` enum plus a separate peer
list, which could not express "Docker *and* these addresses". An upgrade must
keep permitting exactly what it permitted before.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def _policies(monkeypatch: pytest.MonkeyPatch, stored: dict[str, object]) -> tuple:
    """Load the policy list as it would be built from *stored* persistence."""
    module = importlib.import_module('ubo_app.store.services.wyoming')
    monkeypatch.setattr(
        module,
        'read_from_persistent_store',
        lambda key, **kwargs: stored.get(key, kwargs.get('default')),
    )
    return module._load_access_policies(stored.get('wyoming:access_policies'))  # noqa: SLF001


def test_a_fresh_install_permits_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """No keys at all means loopback-only, the safe default."""
    assert _policies(monkeypatch, {}) == ()


def test_local_only_becomes_no_policies(monkeypatch: pytest.MonkeyPatch) -> None:
    """``local-only`` described a loopback listener, which is now zero policies."""
    assert _policies(monkeypatch, {'wyoming:connection_policy': 'local-only'}) == ()


def test_docker_only_becomes_a_docker_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Docker-only install keeps permitting the bridge."""
    module = importlib.import_module('ubo_app.store.services.wyoming')

    policies = _policies(
        monkeypatch,
        {'wyoming:connection_policy': 'docker-home-assistant'},
    )

    assert policies == (
        module.WyomingAccessPolicy(kind=module.WyomingAccessPolicyKind.DOCKER),
    )


def test_an_allowlist_becomes_one_policy_per_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every previously allowed peer survives as its own removable policy."""
    module = importlib.import_module('ubo_app.store.services.wyoming')

    policies = _policies(
        monkeypatch,
        {
            'wyoming:connection_policy': 'allowlist',
            'wyoming:allowed_peers': ['192.168.1.20', '10.0.0.0/24', 'bad-host'],
        },
    )

    assert policies == (
        module.WyomingAccessPolicy(
            kind=module.WyomingAccessPolicyKind.NETWORK,
            value='10.0.0.0/24',
        ),
        module.WyomingAccessPolicy(
            kind=module.WyomingAccessPolicyKind.NETWORK,
            value='192.168.1.20',
        ),
    )


def test_the_new_key_wins_once_it_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    """After the first save the legacy keys are ignored, not merged back in."""
    module = importlib.import_module('ubo_app.store.services.wyoming')

    policies = _policies(
        monkeypatch,
        {
            'wyoming:access_policies': [{'kind': 'docker', 'value': ''}],
            'wyoming:connection_policy': 'allowlist',
            'wyoming:allowed_peers': ['192.168.1.20'],
        },
    )

    assert policies == (
        module.WyomingAccessPolicy(kind=module.WyomingAccessPolicyKind.DOCKER),
    )
