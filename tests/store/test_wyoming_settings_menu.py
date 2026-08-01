"""The Assistant settings entry is a satellite container, not one protocol.

Wyoming lives one level down so further satellite protocols can be added beside
it without moving anything the user has already learned to find.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ubo_app.store.core.types import MenuItemData

SERVICE_DIR = (
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '090-wyoming'
)
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))


def _settings_path(*tail: str) -> tuple[str, ...]:
    """Build a settings navigation path ending in this service's key."""
    return ('menu', 'main', 'settings', 'wyoming:', *tail)


def test_the_settings_entry_opens_the_satellite_list() -> None:
    """Entering Assistant -> Satellites lands on the container, not on Wyoming."""
    import setup  # type: ignore[reportMissingImports]
    from constants import SATELLITES_MENU_ID  # type: ignore[reportMissingImports]

    assert setup._settings_path_matcher(_settings_path()) == SATELLITES_MENU_ID  # noqa: SLF001


def test_deeper_levels_resolve_to_the_pushed_menu() -> None:
    """Wyoming's own menu is reached by the id its row pushes."""
    import setup  # type: ignore[reportMissingImports]
    from constants import WYOMING_MENU_ID  # type: ignore[reportMissingImports]

    path = _settings_path(WYOMING_MENU_ID)

    assert setup._settings_path_matcher(path) == WYOMING_MENU_ID  # noqa: SLF001


def test_unrelated_settings_paths_are_not_claimed() -> None:
    """Another service's settings path must not resolve to a Wyoming menu."""
    import setup  # type: ignore[reportMissingImports]

    assert setup._settings_path_matcher(('menu', 'main', 'settings')) is None  # noqa: SLF001
    assert (
        setup._settings_path_matcher(  # noqa: SLF001
            ('menu', 'main', 'settings', 'speech_recognition:wake_up'),
        )
        is None
    )


def test_the_satellite_list_offers_wyoming() -> None:
    """The container publishes a Wyoming row that pushes the Wyoming menu."""
    import setup  # type: ignore[reportMissingImports]
    from constants import (  # type: ignore[reportMissingImports]
        SATELLITES_MENU_ID,
        WYOMING_MENU_ID,
    )

    dispatched: list[object] = []
    original = setup.store.dispatch
    setup.store.dispatch = dispatched.append  # type: ignore[method-assign]
    try:
        setup._dispatch_satellites_menu()  # noqa: SLF001
    finally:
        setup.store.dispatch = original  # type: ignore[method-assign]

    assert len(dispatched) == 1
    menu = dispatched[0]
    assert getattr(menu, 'menu_id', None) == SATELLITES_MENU_ID
    assert getattr(menu, 'title', None) == 'Satellites'
    items: tuple[MenuItemData, ...] = menu.items  # type: ignore[attr-defined]
    assert [item.label for item in items] == ['Wyoming']
    # The row has to push Wyoming's menu id verbatim, since that is what the
    # deeper-path branch of the matcher resolves back.
    assert items[0].action_id == f'wyoming:goto:{WYOMING_MENU_ID}'
