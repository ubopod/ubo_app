"""Animated splash screen showing the UBO logo sprite-sheet animation."""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.graphics.context_instructions import Color
from kivy.graphics.vertex_instructions import Rectangle
from kivy.uix.widget import Widget

if TYPE_CHECKING:
    from collections.abc import Callable

_SPRITE_SHEET = str(
    Path(__file__).parent / 'assets' / 'ubo_logo_sprites.png',
)
_FADE_DURATION = 0.3
_FRAME_RATE = 1000 / 70  # ~14.3fps, matching GIF's 70ms frame delay
_FRAME_SIZE = 240  # each frame is 240x240 in the sprite sheet
_FRAME_COUNT = 90
_GRID_COLS = math.ceil(math.sqrt(_FRAME_COUNT))


class AnimatedSplashOverlay(Widget):
    """Full-screen overlay that plays the UBO logo animation from a sprite sheet."""

    def __init__(self: AnimatedSplashOverlay, **kwargs: object) -> None:
        """Initialize the splash overlay."""
        super().__init__(**kwargs)
        self._is_dismissed = False
        self._frame_event: object | None = None
        self._frame_index = 0

        # Load sprite sheet and extract frame textures via grid regions
        sheet_image = CoreImage(_SPRITE_SHEET)
        sheet_tex = sheet_image.texture
        self._textures = []
        for i in range(_FRAME_COUNT):
            col = i % _GRID_COLS
            row = i // _GRID_COLS
            # Kivy texture origin is bottom-left, sprite sheet origin is top-left
            # Row 0 in sheet = top = highest y in texture
            tex_y = sheet_tex.height - (row + 1) * _FRAME_SIZE
            region = sheet_tex.get_region(
                col * _FRAME_SIZE,
                tex_y,
                _FRAME_SIZE,
                _FRAME_SIZE,
            )
            self._textures.append(region)

        with self.canvas:
            Color(1, 1, 1, 1)
            self._rect = Rectangle(
                texture=self._textures[0],
                size=self.size,
                pos=self.pos,
            )

        self.bind(size=self._on_resize, pos=self._on_resize)

        # Start frame cycling
        self._frame_event = Clock.schedule_interval(
            self._advance_frame,
            1.0 / _FRAME_RATE,
        )

    def _advance_frame(
        self: AnimatedSplashOverlay,
        _dt: float,
    ) -> bool | None:
        """Advance to the next sprite frame."""
        if self._is_dismissed:
            return False
        self._frame_index = (self._frame_index + 1) % _FRAME_COUNT
        self._rect.texture = self._textures[self._frame_index]
        return None

    def _on_resize(self: AnimatedSplashOverlay, *_args: object) -> None:
        """Update rectangle size and position."""
        self._rect.size = self.size
        self._rect.pos = self.pos

    def dismiss(
        self: AnimatedSplashOverlay,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        """Fade out and call on_complete when done."""
        self._is_dismissed = True
        self.stop_animation()
        anim = Animation(opacity=0, duration=_FADE_DURATION)
        if on_complete:
            anim.bind(on_complete=lambda *_args: on_complete())
        anim.start(self)

    def stop_animation(self: AnimatedSplashOverlay) -> None:
        """Stop the frame cycling."""
        if self._frame_event is not None:
            self._frame_event.cancel()  # pyright: ignore[reportAttributeAccessIssue]
            self._frame_event = None
