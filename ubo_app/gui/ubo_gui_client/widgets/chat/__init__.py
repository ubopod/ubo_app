"""Chat overlay widget for the GUI client.

This is a *pure renderer*. It receives a fully-resolved ``ChatViewData`` (a
list of bubbles) and only draws it. All conversation logic — history,
who-said-what, styling, audio data — lives in the Redux store.

Layout: every bubble's *center* is pinned to the L1/L2/L3 button-row grid
(rows 59px apart, matching the home menu). A taller neighbour pushes the
next bubble up by extra whole rows so they never overlap. The renderer
owns the scroll offset — ↑/↓ pan the column by one whole row at a time, so
the centers stay on the grid and every on-screen bubble keeps an arrow at
a fixed button row. A message taller than the screen pans fully into view
across several steps.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

from kivy.clock import Clock
from kivy.graphics import (
    Color,
    Ellipse,
    Line,
    Rectangle,
    RoundedRectangle,
    Triangle,
)
from kivy.metrics import dp
from kivy.properties import (
    BooleanProperty,
    ColorProperty,
    ListProperty,
    NumericProperty,
    StringProperty,
)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.stencilview import StencilView
from kivy.uix.widget import Widget
from ubo_gui.menu.types import ActionItem

from ubo_gui_client.gui_utils import UboPageWidget

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

logger = logging.getLogger(__name__)

# Layout constants (device screen is 240x240).
_BUBBLE_WIDTH = dp(158)
_SIDE_MARGIN = dp(6)
_LEFT_GUTTER = dp(12)  # room for the pointer triangle on left bubbles
_SCROLLBAR_GUTTER = dp(16)  # right inset so bubbles clear the scrollbar
_POINTER_WIDTH = dp(7)
_POINTER_HEIGHT = dp(12)
_BUBBLE_RADIUS = dp(9)
_BUBBLE_PADDING_X = dp(8)
_BUBBLE_PADDING_Y = dp(6)
_MIN_BUBBLE_GAP = dp(6)  # minimum gap kept between stacked bubbles
_WAVEFORM_HEIGHT = dp(26)
_SCROLLBAR_WIDTH = dp(4)
_SCROLLBAR_COLOR = '#5b9bd5'

# L1/L2/L3 hardware-button row geometry — must match the general menu so a
# bubble's pointer arrow lines up with the same row a home-menu item sits
# on. The menu lays 3 items of MENU_ITEM_HEIGHT(52) + MENU_ITEM_GAP(7) in
# the region between the dp(34) header and dp(36) footer of the 240px
# screen, giving fixed row centers at y = 62 (L3), 121 (L2), 180 (L1).
_BUTTON_FOOTER_H = dp(36)
_BUTTON_ITEM_H = dp(52)
_BUTTON_GAP = dp(7)
_ROW_PITCH = _BUTTON_ITEM_H + _BUTTON_GAP  # vertical distance between rows
_SLOT0_CENTER = _BUTTON_FOOTER_H + _BUTTON_ITEM_H / 2  # L3 (bottom) row center
_VISIBLE_SLOTS = 3  # L3, L2, L1
_SCROLL_STEP = _ROW_PITCH  # one whole row panned per ↑/↓ press


def _hex_to_rgba(
    hex_color: str,
    alpha: float = 1.0,
) -> tuple[float, float, float, float]:
    """Convert a ``#rrggbb`` string to an rgba tuple."""
    cleaned = (hex_color or '#000000').lstrip('#')
    if len(cleaned) == 3:  # noqa: PLR2004
        cleaned = ''.join(channel * 2 for channel in cleaned)
    try:
        red = int(cleaned[0:2], 16) / 255
        green = int(cleaned[2:4], 16) / 255
        blue = int(cleaned[4:6], 16) / 255
    except ValueError:
        return (1.0, 1.0, 1.0, alpha)
    return (red, green, blue, alpha)


def _unwrap_waveform(bubble: object) -> list[float]:
    """Unwrap a proto ``ChatBubbleData.waveform`` wrapper into a float list."""
    wrapper = getattr(bubble, 'waveform', None)
    if wrapper is None:
        return []
    return list(getattr(wrapper, 'items', []) or [])


class ChatWaveform(Widget):
    """An audio clip's waveform — a row of vertical bars drawn on the canvas.

    ``is_playing`` only changes the bars' opacity (bright when playing, dim
    when stopped). It deliberately does not animate so window snapshots stay
    deterministic.
    """

    bars: list[float] = ListProperty()
    bar_color: tuple[float, ...] = ColorProperty((1, 1, 1, 1))
    is_playing: bool = BooleanProperty(default=False)

    def __init__(self, **kwargs: object) -> None:
        """Initialize the waveform widget."""
        super().__init__(**kwargs)
        self.bind(
            pos=self._redraw,
            size=self._redraw,
            bars=self._redraw,
            is_playing=self._redraw,
            bar_color=self._redraw,
        )

    def _redraw(self, *_: object) -> None:
        self.canvas.clear()
        bars = list(self.bars)
        if not bars or self.width <= 0:
            return
        count = len(bars)
        gap = dp(2)
        bar_width = max(dp(1.5), (self.width - gap * (count - 1)) / count)
        red, green, blue, base_alpha = self.bar_color
        alpha = base_alpha if self.is_playing else base_alpha * 0.4
        with self.canvas:
            Color(red, green, blue, alpha)
            for index, value in enumerate(bars):
                bar_height = max(dp(2), min(1.0, value) * self.height)
                x = self.x + index * (bar_width + gap)
                y = self.center_y - bar_height / 2
                RoundedRectangle(
                    pos=(x, y),
                    size=(bar_width, bar_height),
                    radius=[(bar_width / 2, bar_width / 2)],
                )


class ChatBubble(BoxLayout):
    """A single speech bubble (text or audio).

    A fixed-width rounded box that hugs its content; the parent
    ``ChatWidget`` positions it. ``text``, ``is_playing`` and ``waveform``
    are reactive — setting them updates the bubble in place so streamed
    text grows it smoothly.
    """

    message_id: str = StringProperty()
    text: str = StringProperty()
    kind: str = StringProperty('text')
    alignment: str = StringProperty('left')
    bubble_color: tuple[float, ...] = ColorProperty((0.17, 0.18, 0.22, 1))
    text_color: tuple[float, ...] = ColorProperty((1, 1, 1, 1))
    is_playing: bool = BooleanProperty(default=False)
    waveform: list[float] = ListProperty()

    def __init__(self, **kwargs: object) -> None:
        """Build the bubble from its data."""
        super().__init__(
            orientation='vertical',
            size_hint=(None, None),
            width=_BUBBLE_WIDTH,
            padding=(_BUBBLE_PADDING_X, _BUBBLE_PADDING_Y),
            **kwargs,
        )
        # Button-row index this bubble's center sits on (may be off-screen),
        # and the L1/L2/L3 slot its arrow is drawn at (-1 = none).
        self.center_slot: int = 0
        self.arrow_slot: int = -1

        if self.kind == 'audio':
            waveform = ChatWaveform(
                bars=list(self.waveform),
                bar_color=self.text_color,
                is_playing=self.is_playing,
                size_hint_y=None,
                height=_WAVEFORM_HEIGHT,
            )
            self._content: Widget = waveform
            self.bind(
                is_playing=waveform.setter('is_playing'),
                waveform=waveform.setter('bars'),
            )
        else:
            label = Label(
                text=self.text,
                color=self.text_color,
                font_size=dp(14),
                halign='left',
                valign='top',
                size_hint_y=None,
            )
            label.bind(
                width=lambda widget, width: setattr(
                    widget,
                    'text_size',
                    (width, None),
                ),
                texture_size=lambda widget, size: setattr(
                    widget,
                    'height',
                    size[1],
                ),
            )
            self._content = label
            self.bind(text=label.setter('text'))
        self.add_widget(self._content)
        self.bind(minimum_height=self.setter('height'))
        self.bind(pos=self._redraw, size=self._redraw)

    def update_from(self, source: object) -> None:
        """Refresh the mutable fields of this bubble from fresh view data."""
        if self.kind == 'audio':
            self.is_playing = bool(getattr(source, 'is_playing', False))
            self.waveform = _unwrap_waveform(source)
        else:
            self.text = getattr(source, 'text', '') or ''

    def _redraw(self, *_: object) -> None:
        self.canvas.before.clear()
        red, green, blue, alpha = self.bubble_color
        with self.canvas.before:
            Color(red, green, blue, alpha)
            RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[_BUBBLE_RADIUS],
            )


class ChatWidget(UboPageWidget):
    """The chat overlay — bubbles pinned to the L1/L2/L3 row grid, scrollable.

    ``UboPageWidget`` is a Kivy ``Screen`` (a ``RelativeLayout``), so all
    children and canvas drawing live inside a single ``FloatLayout`` root
    that fills the screen via ``size_hint``. Bubbles are positioned
    manually so pointer placement always reads up-to-date geometry.
    """

    total_bubbles: int = NumericProperty(0)

    def __init__(self, **kwargs: object) -> None:
        """Initialize the chat overlay frame."""
        super().__init__(**kwargs)
        self._bubbles: list[ChatBubble] = []
        # Pixel scroll offset (always a whole number of row pitches).
        self._scroll = 0.0
        self._scroll_min = 0.0
        self._scroll_max = 0.0
        # While pinned, every relayout snaps to the newest message's end.
        self._pin_bottom = True
        # Set by the view renderer — dispatches ChatToggleAudioPlaybackAction.
        self.toggle_audio_callback: Callable[[str], None] | None = None

        # Single root that fills the Screen via size_hint (1, 1).
        self._root = FloatLayout()
        with self._root.canvas.before:
            Color(0, 0, 0, 1)
            self._bg_rect = Rectangle()

        # Viewport clips overflowing bubbles; bubbles are its direct,
        # manually-positioned children.
        self._viewport = StencilView(size_hint=(1, 1))
        self._root.add_widget(self._viewport)
        self.add_widget(self._root)

        self._root.bind(pos=self._relayout, size=self._relayout)
        self._viewport.bind(pos=self._relayout, size=self._relayout)
        Clock.schedule_once(self._relayout, 0)

    # -- public API used by the view renderer --------------------------------

    def set_view_data(self, bubbles: Iterable[object]) -> None:
        """Render the bubbles from a ``ChatViewData``.

        When the message set is unchanged (streaming text, toggling audio)
        existing bubbles are updated in place so the widget tree is not
        rebuilt — keeping streaming smooth. Any store update snaps the view
        back to the end of the newest message.
        """
        sources = list(bubbles)

        reusable = len(sources) == len(self._bubbles) and all(
            widget.message_id == (getattr(source, 'message_id', '') or '')
            for widget, source in zip(self._bubbles, sources, strict=True)
        )
        if reusable:
            for widget, source in zip(self._bubbles, sources, strict=True):
                widget.update_from(source)
        else:
            self._viewport.clear_widgets()
            self._bubbles = []
            for source in sources:
                widget = self._create_bubble(source)
                self._bubbles.append(widget)
                self._viewport.add_widget(widget)

        self.total_bubbles = len(self._bubbles)
        self._pin_bottom = True  # snap to the newest message
        Clock.schedule_once(self._relayout, 0)

    def go_up(self) -> None:
        """Scroll toward older content (↑ key)."""
        self._pin_bottom = False
        self._scroll += _SCROLL_STEP
        self._relayout()

    def go_down(self) -> None:
        """Scroll toward newer content (↓ key)."""
        self._pin_bottom = False
        self._scroll -= _SCROLL_STEP
        self._relayout()

    def get_item(self, index: int) -> ActionItem | None:
        """Return the L1/L2/L3 action for a button press.

        ``index`` 0/1/2 maps to L1/L2/L3. An audio bubble whose arrow is at
        that button's row returns an action that toggles its playback;
        every other case returns ``None`` (the press is inert).
        """
        slot = (_VISIBLE_SLOTS - 1) - index  # L1→top slot, L3→bottom slot
        for bubble in self._bubbles:
            if bubble.arrow_slot != slot:
                continue
            if bubble.kind != 'audio':
                return None
            message_id = bubble.message_id

            def _toggle(_message_id: str = message_id) -> None:
                if self.toggle_audio_callback is not None:
                    self.toggle_audio_callback(_message_id)

            return ActionItem(label='', action=_toggle)
        return None

    def _create_bubble(self, source: object) -> ChatBubble:
        """Build a ``ChatBubble`` widget from a proto ``ChatBubbleData``."""
        bubble = ChatBubble(
            message_id=getattr(source, 'message_id', '') or '',
            text=getattr(source, 'text', '') or '',
            kind=getattr(source, 'kind', 'text') or 'text',
            alignment=getattr(source, 'alignment', 'left') or 'left',
            bubble_color=_hex_to_rgba(
                getattr(source, 'background_color', '#2b2f38'),
            ),
            text_color=_hex_to_rgba(getattr(source, 'color', '#ffffff')),
            is_playing=bool(getattr(source, 'is_playing', False)),
            waveform=_unwrap_waveform(source),
        )
        # The height settles over a few frames as the label wraps — re-run
        # the manual layout whenever it changes.
        bubble.bind(height=self._relayout)
        return bubble

    # -- layout --------------------------------------------------------------

    def _arrow_y(self, slot: int) -> float:
        """Screen Y of the L1/L2/L3 arrow row for ``slot`` (0=L3..2=L1)."""
        return self._root.y + _SLOT0_CENTER + slot * _ROW_PITCH

    def _relayout(self, *_: object) -> None:
        """Pin bubble centers to the row grid, apply scroll, draw overlays."""
        self._bg_rect.pos = self._root.pos
        self._bg_rect.size = self._root.size

        for bubble in self._bubbles:
            bubble.arrow_slot = -1
            bubble.center_slot = 0

        viewport_h = self._viewport.height
        total = len(self._bubbles)
        if total and viewport_h > 0:
            # Grid offset (whole rows above the newest) for each center: a
            # taller neighbour bumps the next bubble up by extra rows.
            grid = [0] * total
            for index in range(total - 2, -1, -1):
                needed = (
                    self._bubbles[index].height
                    + self._bubbles[index + 1].height
                ) / 2 + _MIN_BUBBLE_GAP
                grid[index] = grid[index + 1] + max(
                    1,
                    math.ceil(needed / _ROW_PITCH),
                )

            base = self._root.y + _SLOT0_CENTER  # newest center at scroll 0
            newest_half = self._bubbles[-1].height / 2
            oldest_half = self._bubbles[0].height / 2
            # Scroll bounds snapped to whole rows so centers stay on grid.
            self._scroll_min = min(
                0.0,
                math.floor((_SLOT0_CENTER - newest_half) / _ROW_PITCH)
                * _ROW_PITCH,
            )
            self._scroll_max = max(
                0.0,
                math.ceil(
                    (
                        _SLOT0_CENTER
                        + grid[0] * _ROW_PITCH
                        + oldest_half
                        - viewport_h
                    )
                    / _ROW_PITCH,
                )
                * _ROW_PITCH,
            )
            if self._pin_bottom:
                self._scroll = self._scroll_min
            self._scroll = min(
                max(self._scroll, self._scroll_min),
                self._scroll_max,
            )

            scroll_steps = round(self._scroll / _ROW_PITCH)
            for index, bubble in enumerate(self._bubbles):
                bubble.center_slot = grid[index] - scroll_steps
                bubble.center_y = base + bubble.center_slot * _ROW_PITCH
                if bubble.alignment == 'right':
                    bubble.right = self._viewport.right - _SCROLLBAR_GUTTER
                else:
                    bubble.x = self._viewport.x + _LEFT_GUTTER

            self._assign_arrows()
        else:
            self._scroll_min = 0.0
            self._scroll_max = 0.0

        self._draw_overlays()

    def _assign_arrows(self) -> None:
        """Give each on-screen bubble one arrow at a fixed L1/L2/L3 row.

        A bubble whose center is on screen sits exactly on a button row —
        its arrow goes there. A bubble taller than the screen (center
        off-screen) keeps an arrow at the nearest on-screen row its body
        still covers, so it never loses its pointer while being scrolled.
        """
        margin = _BUBBLE_RADIUS + _POINTER_HEIGHT / 2
        for bubble in self._bubbles:
            slot = bubble.center_slot
            if 0 <= slot < _VISIBLE_SLOTS:
                bubble.arrow_slot = slot
                continue
            covered = [
                candidate
                for candidate in range(_VISIBLE_SLOTS)
                if bubble.y + margin
                <= self._arrow_y(candidate)
                <= bubble.top - margin
            ]
            if covered:
                bubble.arrow_slot = min(
                    covered,
                    key=lambda candidate: abs(candidate - slot),
                )

    def _draw_overlays(self) -> None:
        """Draw the pointer arrows + scrollbar, or the empty placeholder."""
        self._root.canvas.after.clear()
        if self._bubbles:
            self._draw_pointers()
            self._draw_scrollbar()
        else:
            self._draw_empty_placeholder()

    def _draw_empty_placeholder(self) -> None:
        """Draw a large chat-bubble icon while the conversation is empty.

        A fresh session has no bubbles yet; without this the screen is just
        black, which reads as broken rather than "waiting for a message".
        """
        center_x = self._root.center_x
        center_y = self._root.center_y
        width = dp(104)
        height = dp(72)
        tail = dp(15)
        left = center_x - width / 2
        bottom = center_y - height / 2 + tail / 2
        with self._root.canvas.after:
            Color(0.26, 0.28, 0.34, 1)
            RoundedRectangle(
                pos=(left, bottom),
                size=(width, height),
                radius=[dp(16)],
            )
            # Tail pointing down-left, overlapping the body so it joins it.
            Triangle(
                points=[
                    left + dp(20),
                    bottom + dp(4),
                    left + dp(44),
                    bottom + dp(4),
                    left + dp(8),
                    bottom - tail,
                ],
            )
            # Three dots — the universal "chat / waiting" glyph.
            Color(0.52, 0.54, 0.60, 1)
            dot = dp(12)
            spacing = dp(22)
            dot_y = bottom + height / 2 - dot / 2
            for offset in (-spacing, 0.0, spacing):
                Ellipse(
                    pos=(center_x + offset - dot / 2, dot_y),
                    size=(dot, dot),
                )

    def _draw_pointers(self) -> None:
        """Draw each bubble's pointer arrow at its assigned fixed row."""
        with self._root.canvas.after:
            for bubble in self._bubbles:
                if bubble.arrow_slot < 0:
                    continue
                center_y = self._arrow_y(bubble.arrow_slot)
                tip_x = bubble.x - _POINTER_WIDTH
                base_x = bubble.x + dp(1)
                Color(*bubble.bubble_color)
                Triangle(
                    points=[
                        tip_x,
                        center_y,
                        base_x,
                        center_y + _POINTER_HEIGHT / 2,
                        base_x,
                        center_y - _POINTER_HEIGHT / 2,
                    ],
                )

    def _draw_scrollbar(self) -> None:
        span = self._scroll_max - self._scroll_min
        if span <= 0 or not self._bubbles:
            return
        track_x = self._root.right - _SIDE_MARGIN - _SCROLLBAR_WIDTH
        track_top = self._root.top - _SIDE_MARGIN
        track_bottom = self._root.y + _SIDE_MARGIN
        track_height = track_top - track_bottom
        viewport_h = self._viewport.height
        visible_fraction = min(1.0, viewport_h / (viewport_h + span))
        thumb_height = max(dp(14), track_height * visible_fraction)
        # scroll at min → newest end shown → thumb at the bottom.
        progress = (self._scroll - self._scroll_min) / span
        thumb_y = track_bottom + progress * (track_height - thumb_height)
        with self._root.canvas.after:
            Color(1, 1, 1, 0.18)
            Line(
                points=[
                    track_x + _SCROLLBAR_WIDTH / 2,
                    track_bottom,
                    track_x + _SCROLLBAR_WIDTH / 2,
                    track_top,
                ],
                width=dp(1),
            )
            Color(*_hex_to_rgba(_SCROLLBAR_COLOR))
            RoundedRectangle(
                pos=(track_x, thumb_y),
                size=(_SCROLLBAR_WIDTH, thumb_height),
                radius=[_SCROLLBAR_WIDTH / 2],
            )
