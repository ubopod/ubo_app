"""Pure option lists for the ``kiosk:set-output`` bindable action's parameters.

The action is registered once and takes two parameters — which output, and what
it should show. These build the ``(value, label)`` choices the parameter prompt
offers, read at prompt time so a dashboard added a moment ago is present.

Kept free of the store so it can be reasoned about — and tested — on its own;
``setup.py`` supplies the port table and the live dashboard list.
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


def port_options(
    ports: Sequence[tuple[str, str, str, str]],
) -> list[tuple[str, str]]:
    """Return the ``(value, label)`` choices for the output parameter."""
    return [
        (field_name, label) for field_name, _path_key, _drm_name, label in ports
    ]


def target_options(
    dashboards: Sequence[KioskDashboard],
) -> list[tuple[str, str]]:
    """Return the ``(value, label)`` choices for what an output should show.

    The value is the tail of the menu-action id the selection already has
    (``terminal``, ``off``, ``dash:<id>``), so the bindable factory can compose
    the id rather than reimplement the dispatch.
    """
    return [
        ('terminal', 'Terminal'),
        ('off', 'Off'),
        *(
            (f'dash:{dashboard.id}', name)
            for dashboard, name in zip(
                dashboards,
                _unique_names(dashboards),
                strict=True,
            )
        ),
    ]
