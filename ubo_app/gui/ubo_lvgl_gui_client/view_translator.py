"""Translate betterproto ViewData/StatusBarData into bridge dataclasses.

This is the phase-1 analogue of the Kivy ``view_renderer.py``: it maps the gRPC
view model onto the C renderer's view model. In phase 2 the same mapping is
rewritten in C against the decoded proto. The C renderer ignores ``action_id``
(navigation/selection is driven entirely by forwarding keypad presses).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import betterproto
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


def _basic_to_str(b: betterproto.Message) -> str | None:
    """Stringify a betterproto BasicType oneof (bytes are not carried)."""
    name, val = betterproto.which_one_of(b, 'basic_type')
    if name == 'bytes' or val is None:
        return None
    if name == 'bool':
        return 'true' if val else 'false'
    return str(val)


def _prop_value_to_str(pv: betterproto.Message) -> str | None:
    """Stringify a RenderViewData PropsValue (scalar, or newline-joined list)."""
    name, val = betterproto.which_one_of(pv, 'props_value')
    if name == 'basic_type':
        return _basic_to_str(val) if val is not None else None
    if name == 'list':
        items = cast('list[Any]', getattr(val, 'items', None) or [])
        parts: list[str] = []
        for x in items:
            s = _basic_to_str(x)
            if s is not None:
                parts.append(s)
        return '\n'.join(parts)
    return None


def _props(props: object) -> list[bridge.RenderProp]:
    """Flatten a RenderViewData props map into stringified key/value pairs."""
    mapping = getattr(props, 'items', None) or {}
    out = []
    for key, pv in mapping.items():
        value = _prop_value_to_str(pv)
        if value is not None:
            out.append(bridge.RenderProp(key=key, value=value))
    return out


def _prop_bytes(props: object, key: str) -> bytes | None:
    """Return a bytes-typed scalar prop (e.g. image_viewer's raw RGB image)."""
    mapping = getattr(props, 'items', None) or {}
    pv = mapping.get(key)
    if pv is None:
        return None
    name, val = betterproto.which_one_of(pv, 'props_value')
    if name != 'basic_type' or val is None:
        return None
    bname, bval = betterproto.which_one_of(val, 'basic_type')
    return bval if bname == 'bytes' else None


def _prop_int(props: object, key: str) -> int | None:
    """Return an int-valued scalar prop (e.g. image_viewer's width/height)."""
    mapping = getattr(props, 'items', None) or {}
    pv = mapping.get(key)
    if pv is None:
        return None
    value = _prop_value_to_str(pv)
    if value is None:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


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


def frame_stream_id(view: object) -> str | None:
    """Return the stream_id when `view` is a live frame_stream view, else None."""
    if isinstance(view, RenderViewData) and view.kind == 'frame_stream':
        return view.stream_id or None
    return None


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
                placeholder=_strip_markup(view.placeholder),
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
        renderer.render_render(
            bridge.RenderView(
                show_status_bar=bool(view.show_status_bar),
                kind=view.kind or '',
                title=_strip_markup(view.title) or '',
                props=_props(view.props),
                items=[_menu_item(it) for it in _items(view.items)],
                stream_id=view.stream_id or None,
            ),
        )
        # image_viewer ships its image inline (a bytes prop); push it now.
        if view.kind == 'image_viewer':
            image = _prop_bytes(view.props, 'image')
            width = _prop_int(view.props, 'width')
            height = _prop_int(view.props, 'height')
            if image and width and height:
                renderer.update_frame(image, width, height)
