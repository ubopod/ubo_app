"""Pure enumeration of the kiosk output selections offered for binding.

Each entry is a ``(key, label)`` pair for the bindable-actions registry, which
backs both the voice-command Action dropdown (Settings ▸ Accessibility ▸ Voice
Shortcuts) and the Infrared "Add Keys" dropdown. The key is deliberately the
same string as the corresponding *menu* action id, so the bindable factory can
delegate through ``ExecuteMenuActionAction`` instead of duplicating dispatch.

Kept free of the store so it can be reasoned about — and tested — on its own;
``setup.py`` supplies the port table and does the registering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_app.store.services.kiosk import KioskDashboard


def _unique_names(dashboards: Sequence[KioskDashboard]) -> list[str]:
    """Return each dashboard's display name, suffixed so no two collide.

    Dashboard names are free text, so two can easily be identical.
    ``register_bindable_action`` rejects a label already held by another key, and
    that exception would propagate out of the autorun that registers these and
    take the dashboards menu down with it. Repeats therefore become ``name (2)``,
    ``name (3)``, … in dashboard order, which is stable across runs.
    """
    counts: dict[str, int] = {}
    names: list[str] = []
    for dashboard in dashboards:
        counts[dashboard.name] = counts.get(dashboard.name, 0) + 1
        occurrence = counts[dashboard.name]
        names.append(
            dashboard.name if occurrence == 1 else f'{dashboard.name} ({occurrence})',
        )
    return names


def static_bindable_entries(
    ports: Sequence[tuple[str, str, str, str]],
) -> list[tuple[str, str]]:
    """Return the dashboard-independent ``(key, label)`` entries, one set per port."""
    return [
        entry
        for field_name, _path_key, _drm_name, label in ports
        for entry in (
            (f'kiosk:set:{field_name}:terminal', f'Kiosk: Terminal on {label}'),
            (f'kiosk:set:{field_name}:off', f'Kiosk: Turn Off {label}'),
        )
    ]


def dashboard_bindable_entries(
    dashboards: Sequence[KioskDashboard],
    ports: Sequence[tuple[str, str, str, str]],
) -> list[tuple[str, str]]:
    """Return a ``(key, label)`` entry per (dashboard, port) pair.

    Re-derived whenever the dashboard set changes, so the keys of deleted
    dashboards can be unregistered and the new ones registered in one pass.
    """
    names = _unique_names(dashboards)
    return [
        (
            f'kiosk:set:{field_name}:dash:{dashboard.id}',
            f'Kiosk: Show {name} on {label}',
        )
        for dashboard, name in zip(dashboards, names, strict=True)
        for field_name, _path_key, _drm_name, label in ports
    ]
