"""Selectors that produce rendered UI types from state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_gui.menu.types import (
    ActionItem,
    ApplicationItem,
    SubMenuItem,
)

from ubo_app.store.core.selectors import (
    select_breadcrumb,
    select_can_go_down,
    select_can_go_up,
    select_current_items,
    select_current_page_index,
    select_current_title,
    select_is_at_home,
    select_stack_depth,
    select_top_stack_item,
    select_total_pages,
)
from ubo_app.store.core.types import ApplicationStackItem
from ubo_app.store.core.ui_types import (
    RenderedApplication,
    RenderedItem,
    RenderedItemType,
    RenderedPage,
    RenderedView,
)

if TYPE_CHECKING:
    from ubo_gui.menu.types import Item

    from ubo_app.store.main import RootState


def _resolve_value(value: str | None | object) -> str:
    """Resolve a value that may be a callable or a direct value."""
    if value is None:
        return ''
    if callable(value):
        result = value()
        return str(result) if result is not None else ''
    return str(value)


def _infer_item_type(item: Item) -> RenderedItemType:
    """Infer the RenderedItemType from a ubo_gui Item."""
    if isinstance(item, SubMenuItem):
        return RenderedItemType.SUBMENU
    if isinstance(item, ApplicationItem):
        return RenderedItemType.APPLICATION
    if isinstance(item, ActionItem):
        return RenderedItemType.ACTION
    return RenderedItemType.ACTION


def _item_to_rendered(item: Item | None) -> RenderedItem | None:
    """Convert ubo_gui Item to RenderedItem."""
    if item is None:
        return None

    # Resolve potentially callable values
    label = _resolve_value(item.label)
    icon = _resolve_value(item.icon)
    color = _resolve_value(item.color) or '#FFFFFF'
    background_color = _resolve_value(item.background_color)
    is_short = item.is_short if isinstance(item.is_short, bool) else False

    return RenderedItem(
        type=_infer_item_type(item),
        key=item.key,
        label=label,
        icon=icon,
        color=color,
        background_color=background_color if background_color else None,
        is_short=is_short,
        is_disabled=False,
        progress=item.progress,
        opacity=item.opacity if item.opacity is not None else 1.0,
    )


def select_rendered_page(state: RootState) -> RenderedPage:
    """Convert current menu state to RenderedPage."""
    items = select_current_items(state)
    rendered_items = tuple(_item_to_rendered(item) for item in items)

    return RenderedPage(
        items=rendered_items,
        title=select_current_title(state),
        page_index=select_current_page_index(state),
        total_pages=select_total_pages(state),
        can_go_up=select_can_go_up(state),
        can_go_down=select_can_go_down(state),
        breadcrumb=select_breadcrumb(state),
    )


def select_rendered_application(state: RootState) -> RenderedApplication | None:
    """Get rendered application if one is on top of the stack."""
    top = select_top_stack_item(state)
    if not isinstance(top, ApplicationStackItem):
        return None

    return RenderedApplication(
        application_id=top.application_id,
        instance_id=top.instance_id,
        title=top.title,
        content={
            'initialization_args': top.initialization_args,
            'initialization_kwargs': top.initialization_kwargs,
        },
    )


def select_rendered_view(state: RootState) -> RenderedView:
    """Get complete rendered view for the current state."""
    top = select_top_stack_item(state)
    is_application = isinstance(top, ApplicationStackItem)
    is_menu = not is_application

    page = select_rendered_page(state) if is_menu else None
    application = select_rendered_application(state) if is_application else None

    return RenderedView(
        is_menu=is_menu,
        is_application=is_application,
        page=page,
        application=application,
        stack_depth=select_stack_depth(state),
        is_at_home=select_is_at_home(state),
        can_go_back=select_stack_depth(state) > 0,
        is_header_visible=state.main.is_header_visible,
        is_footer_visible=state.main.is_footer_visible,
    )
