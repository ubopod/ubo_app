"""Menu item styling parameters (Kivy-free)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, TypeAlias

from ubo_app.colors import SUCCESS_COLOR

if TYPE_CHECKING:
    from collections.abc import Sequence

ItemParameters: TypeAlias = dict[Literal['background_color', 'color', 'icon'], str]

SELECTED_ITEM_PARAMETERS: ItemParameters = {
    'background_color': SUCCESS_COLOR,
    'icon': '󰱒',
}
UNSELECTED_ITEM_PARAMETERS: ItemParameters = {
    'icon': '󰄱',
}


def build_selection_menu(  # noqa: PLR0913
    *,
    options: Sequence[tuple[str, str, str]],
    selected_key: str,
    menu_id: str,
    title: str,
    heading: str | None = None,
    sub_heading: str | None = None,
) -> None:
    """Build and dispatch a 'select one from N' dynamic menu.

    Each option is a tuple of (key, label, action_id). The option whose key
    matches ``selected_key`` is rendered with the selected style; others get
    the unselected style.
    """
    from ubo_app.store.core.types import MenuItemData, UpdateDynamicMenuAction
    from ubo_app.store.main import store

    items = tuple(
        MenuItemData(
            key=key,
            label=label,
            icon=SELECTED_ITEM_PARAMETERS['icon']
            if key == selected_key
            else UNSELECTED_ITEM_PARAMETERS['icon'],
            action_id=action_id,
            background_color=SELECTED_ITEM_PARAMETERS.get('background_color')
            if key == selected_key
            else None,
        )
        for key, label, action_id in options
    )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=menu_id,
            title=title,
            heading=heading,
            sub_heading=sub_heading,
            items=items,
            placeholder='',
        ),
    )
