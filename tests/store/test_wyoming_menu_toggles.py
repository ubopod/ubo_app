"""On/off rows read as checkboxes: marked is enabled, blank is disabled.

Labels stay bare because the checkbox already carries the state, and the LCD is
narrow enough that a trailing ``: On``/``: Off`` pushes real labels off the edge.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ubo_app.store.services.wyoming import (
    WyomingAccessPolicy,
    WyomingAccessPolicyKind,
    WyomingState,
)

SERVICE_DIR = (
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '090-wyoming'
)
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

_POLICIES = (
    WyomingAccessPolicy(
        kind=WyomingAccessPolicyKind.NETWORK,
        value='192.168.1.20',
    ),
)

CHECKED = '\U000f0c52'
UNCHECKED = '\U000f0131'

# The widest label the LCD renders without truncating, measured against the
# labels already shipping in this menu.
_MAX_LABEL_LENGTH = 16


def _items(**kwargs: object) -> dict[str, object]:
    import setup  # type: ignore[reportMissingImports]

    state = WyomingState(**kwargs)  # type: ignore[arg-type]
    return {item.key: item for item in setup._menu_items(state)}  # noqa: SLF001


def test_a_checked_box_means_enabled() -> None:
    """Every on/off row shows a marked checkbox when its option is on."""
    items = _items(
        is_satellite_enabled=True,
        is_engines_enabled=True,
        is_zeroconf_enabled=True,
        access_policies=_POLICIES,
    )

    for key in ('wyoming:satellite', 'wyoming:engines', 'wyoming:zeroconf'):
        assert items[key].icon == CHECKED, key  # type: ignore[attr-defined]


def test_a_blank_box_means_disabled() -> None:
    """Every on/off row shows an empty checkbox when its option is off."""
    items = _items(
        is_satellite_enabled=False,
        is_engines_enabled=False,
        is_zeroconf_enabled=False,
        access_policies=_POLICIES,
    )

    for key in ('wyoming:satellite', 'wyoming:engines', 'wyoming:zeroconf'):
        assert items[key].icon == UNCHECKED, key  # type: ignore[attr-defined]


def test_toggle_labels_do_not_repeat_the_state() -> None:
    """The checkbox is the state, so the label must not say it again."""
    items = _items(
        is_satellite_enabled=True,
        is_engines_enabled=False,
        is_zeroconf_enabled=True,
        access_policies=_POLICIES,
    )

    for key in ('wyoming:satellite', 'wyoming:engines', 'wyoming:zeroconf'):
        label = items[key].label  # type: ignore[attr-defined]
        assert ': On' not in label, key
        assert ': Off' not in label, key


def test_labels_fit_the_screen() -> None:
    """Labels have to fit the LCD rather than being silently truncated."""
    items = _items(
        is_satellite_enabled=True,
        is_engines_enabled=True,
        is_zeroconf_enabled=True,
        access_policies=_POLICIES,
    )

    for key in ('wyoming:satellite', 'wyoming:engines', 'wyoming:zeroconf'):
        label = items[key].label  # type: ignore[attr-defined]
        assert len(label) <= _MAX_LABEL_LENGTH, f'{key}: {label!r}'
