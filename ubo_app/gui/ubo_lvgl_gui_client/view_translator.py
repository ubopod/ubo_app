"""Translate betterproto ViewData/StatusBarData into bridge dataclasses.

This is the phase-1 analogue of the Kivy ``view_renderer.py``: it maps the gRPC
view model onto the C renderer's view model. In phase 2 the same mapping is
rewritten in C against the decoded proto. The C renderer ignores ``action_id``
(navigation/selection is driven entirely by forwarding keypad presses).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_bindings.ubo.v1 import (
    ApplicationViewData,
    HomeViewData,
    InstructionViewData,
    MenuViewData,
    NotificationViewData,
    PromptViewData,
    RenderViewData,
)

from ubo_lvgl_gui_client import bridge

if TYPE_CHECKING:
    from ubo_lvgl_gui_client.bridge import Renderer

# Minimal named-color map (the core also emits '#rrggbb' which passes through).
_NAMED = {
    'white': '#ffffff',
    'black': '#000000',
    'red': '#f44336',
    'green': '#4caf50',
    'blue': '#2196f3',
    'yellow': '#ffeb3b',
    'orange': '#ff9800',
    'gray': '#808080',
    'grey': '#808080',
}


def _color(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith('#'):
        return value
    return _NAMED.get(value.lower())


def _strip_markup(value: str | None) -> str | None:
    """Drop Kivy markup tags, keeping the text/glyph between them.

    E.g. '[size=18dp]x[/size]', '[color=..]g[/color]'. The core renders with Kivy
    markup; LVGL has none, so we flatten to plain text.
    """
    if not value:
        return None
    out = []
    depth = 0
    for ch in value:
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    text = ''.join(out).strip()
    return text or None


# Icons are single glyphs but may also be wrapped in markup.
_icon = _strip_markup


def _items(wrapper: object) -> list:
    """Unwrap a betterproto repeated-field container, dropping None entries.

    Tuples of nullable elements (e.g. ``tuple[MenuItemData | None, ...]``) are
    double-wrapped: ``wrapper.items`` is a list of ``*ItemsItem`` elements whose
    own ``.items`` field holds the real message (or None when absent). Tuples of
    non-nullable elements (home items, status icons) are wrapped only once.
    """
    if wrapper is None:
        return []
    out = []
    for elem in getattr(wrapper, 'items', None) or []:
        if elem is None:
            continue
        leaf = (
            getattr(elem, 'items', None)
            if type(elem).__name__.endswith('ItemsItem')
            else elem
        )
        if leaf is not None:
            out.append(leaf)
    return out


def _menu_item(it: object) -> bridge.MenuItem:
    return bridge.MenuItem(
        key=getattr(it, 'key', '') or '',
        label=_strip_markup(getattr(it, 'label', None)) or '',
        icon=_icon(getattr(it, 'icon', None)),
        color=_color(getattr(it, 'color', None)),
        background_color=_color(getattr(it, 'background_color', None)),
        is_short=bool(getattr(it, 'is_short', False)),
    )


def translate_status_bar(sb: object) -> bridge.StatusBar:
    """Map a betterproto StatusBarData to a bridge.StatusBar."""
    return bridge.StatusBar(
        title=getattr(sb, 'title', '') or '',
        is_recording=bool(getattr(sb, 'is_recording', False)),
        is_replaying=bool(getattr(sb, 'is_replaying', False)),
        is_recording_audio=bool(getattr(sb, 'is_recording_audio', False)),
        progress_notifications=[
            bridge.ProgressNotification(
                id=getattr(p, 'id', '') or '',
                progress=getattr(p, 'progress', None),
                color=_color(getattr(p, 'color', None)),
            )
            for p in _items(getattr(sb, 'progress_notifications', None))
        ],
        clock=getattr(sb, 'clock', '') or '',
        temperature=getattr(sb, 'temperature', None),
        light_level=getattr(sb, 'light_level', None),
        icons=[
            bridge.StatusIcon(
                symbol=_icon(getattr(i, 'symbol', None)) or '',
                color=_color(getattr(i, 'color', None)),
            )
            for i in _items(getattr(sb, 'icons', None))
        ],
    )


def render_view(renderer: Renderer, view: object) -> None:
    """Render a single ViewData via the C renderer."""
    if isinstance(view, HomeViewData):
        renderer.render_home(
            bridge.HomeView(
                show_status_bar=bool(view.show_status_bar),
                items=[_menu_item(it) for it in _items(view.menu_items)],
                cpu_percent=view.cpu_percent or 0.0,
                ram_percent=view.ram_percent or 0.0,
                volume_level=view.volume_level or 0.0,
            ),
        )
    elif isinstance(view, MenuViewData):
        renderer.render_menu(
            bridge.MenuView(
                show_status_bar=bool(view.show_status_bar),
                title=_strip_markup(view.title) or '',
                heading=_strip_markup(view.heading),
                sub_heading=_strip_markup(view.sub_heading),
                items=[_menu_item(it) for it in _items(view.items)],
                page_index=view.page_index or 0,
                total_pages=view.total_pages or 1,
                stack_depth=view.stack_depth or 1,
            ),
        )
    elif isinstance(view, NotificationViewData):
        renderer.render_notification(
            bridge.NotificationView(
                show_status_bar=bool(view.show_status_bar),
                notification_id=view.notification_id or '',
                title=_strip_markup(view.title) or '',
                content=_strip_markup(view.content) or '',
                icon=_icon(view.icon),
                color=_color(view.color),
                items=[_menu_item(it) for it in _items(view.items)],
                page_index=view.page_index or 0,
                total_pages=view.total_pages or 1,
            ),
        )
    elif isinstance(view, InstructionViewData):
        renderer.render_instruction(
            bridge.InstructionView(
                show_status_bar=bool(view.show_status_bar),
                title=_strip_markup(view.title) or '',
                instruction=_strip_markup(view.instruction) or '',
                icon=_icon(view.icon),
                spinner=bool(view.spinner),
                progress_text=_strip_markup(view.progress_text),
                footer_text=_strip_markup(view.footer_text),
            ),
        )
    elif isinstance(view, PromptViewData):
        renderer.render_prompt(
            bridge.PromptView(
                show_status_bar=bool(view.show_status_bar),
                title=_strip_markup(view.title) or '',
                prompt=_strip_markup(view.prompt) or '',
                icon=_icon(view.icon),
                items=[_menu_item(it) for it in _items(view.items)],
            ),
        )
    elif isinstance(view, ApplicationViewData):
        renderer.render_application(
            bridge.ApplicationView(
                show_status_bar=bool(view.show_status_bar),
                application_id=view.application_id or '',
            ),
        )
    elif isinstance(view, RenderViewData):
        # Generic render widgets (qr/text/image/...) are phase 1.5; show a
        # placeholder for now.
        renderer.render_application(
            bridge.ApplicationView(
                show_status_bar=bool(view.show_status_bar),
                application_id=view.kind or 'render',
            ),
        )
