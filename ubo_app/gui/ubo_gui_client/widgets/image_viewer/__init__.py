"""Raw image viewer widget."""

from __future__ import annotations

import pathlib
from enum import StrEnum
from typing import TYPE_CHECKING

from kivy.clock import Clock
from kivy.graphics.texture import Texture
from kivy.lang.builder import Builder
from kivy.metrics import dp
from kivy.properties import (
    AliasProperty,
    NumericProperty,
    ObjectProperty,
    StringProperty,
)
from ubo_gui.menu.types import ActionItem, Item
from ubo_gui.utils import mainthread_if_needed

from ubo_gui_client.constants import HEIGHT, WIDTH
from ubo_gui_client.gui_utils import UboPageWidget

if TYPE_CHECKING:
    from kivy.uix.widget import Widget

ZOOM_FACTOR = 1.1
SCROLL_STEP = 10


class ScrollControl(StrEnum):
    """Enum for scroll control."""

    VERTICAL = 'vertical_scroll'
    HORIZONTAL = 'horizontal_scroll'
    ZOOM = 'zoom_scroll'


class RawImageViewer(UboPageWidget):
    """Kivy widget for displaying raw image."""

    def _get_texture(self) -> Texture | None:
        """Update the image when the image property changes."""
        # The picture arrives over the frame stream, so the widget is built
        # empty and stays that way until the first frame lands.
        if not self.image or self.width <= 0 or self.height <= 0:
            return None
        texture = Texture.create(
            size=(self.width, self.height),
            colorfmt='rgb',
        )
        texture.blit_buffer(
            self.image,
            colorfmt='rgb',
            bufferfmt='ubyte',
        )
        texture.flip_vertical()

        return texture

    active_control: ScrollControl = StringProperty(ScrollControl.VERTICAL)
    width: int = NumericProperty()
    height: int = NumericProperty()
    image: bytes = ObjectProperty()
    texture: Texture = AliasProperty(getter=_get_texture, bind=['image'])

    def update_frame(self, data: bytes, width: int, height: int) -> None:
        """Display a frame-stream image (the `FrameStreamRenderPage` contract).

        `image` is assigned last: `texture` is an `AliasProperty` bound to it,
        so that assignment is what rebuilds the texture — at the new geometry.
        """
        self.width = width
        self.height = height
        self.image = data

    def on_texture(self, instance: RawImageViewer, texture: Texture) -> None:
        """Reset position based on the size of the new texture."""
        _ = instance, texture
        Clock.schedule_once(self._center)

    def on_kv_post(self, base_widget: Widget) -> None:
        """Set position based on the size of the new texture."""
        _ = base_widget
        Clock.schedule_once(self._center)

    def on_size(self, instance: RawImageViewer, value: tuple[int, int]) -> None:
        """Center the image based on new container size."""
        _ = instance, value
        Clock.schedule_once(self._center)

    @mainthread_if_needed
    def _center(self, _: float = 0) -> None:
        if not self.ids.scrollable_widget.width or (
            not self.ids.scrollable_widget.height
        ):
            return  # no frame yet
        zoom_factor = min(
            self.ids.container.width / self.ids.scrollable_widget.width,
            self.ids.container.height / self.ids.scrollable_widget.height,
        )
        self.ids.scrollable_widget.width *= zoom_factor
        self.ids.scrollable_widget.height *= zoom_factor
        self.ids.scrollable_widget.x = (
            self.ids.container.width - self.ids.scrollable_widget.width
        ) / 2
        self.ids.scrollable_widget.y = (
            self.ids.container.height - self.ids.scrollable_widget.height
        ) / 2

    @mainthread_if_needed
    def _apply_limits(self, _: float = 0) -> None:
        self.ids.scrollable_widget.x = min(
            max(
                self.ids.scrollable_widget.x,
                self.ids.container.x
                + self.ids.container.width / 2
                - self.ids.scrollable_widget.width,
            ),
            self.ids.container.x + self.ids.container.width / 2,
        )
        self.ids.scrollable_widget.y = min(
            max(
                self.ids.scrollable_widget.y,
                self.ids.container.y
                + self.ids.container.height / 2
                - self.ids.scrollable_widget.height,
            ),
            self.ids.container.y + self.ids.container.height / 2,
        )

    def _zoom(self, factor: float) -> None:
        center = (
            (
                self.ids.scrollable_widget.x
                - self.ids.container.x
                - self.ids.container.width / 2
            )
            / self.ids.scrollable_widget.width,
            (
                self.ids.scrollable_widget.y
                - self.ids.container.y
                - self.ids.container.height / 2
            )
            / self.ids.scrollable_widget.height,
        )
        self.ids.scrollable_widget.width = max(
            min(self.ids.scrollable_widget.width * factor, dp(self.width) * 10),
            dp(WIDTH) / 2,
        )
        self.ids.scrollable_widget.height = max(
            min(self.ids.scrollable_widget.height * factor, dp(self.height) * 10),
            dp(HEIGHT) / 2,
        )
        self.ids.scrollable_widget.pos = (
            center[0] * self.ids.scrollable_widget.width
            + self.ids.container.x
            + self.ids.container.width / 2,
            center[1] * self.ids.scrollable_widget.height
            + self.ids.container.y
            + self.ids.container.height / 2,
        )

    def go_up(self) -> None:
        """Scroll up, left or zoom in the image based on the active control."""
        match self.active_control:
            case ScrollControl.VERTICAL:
                self.ids.scrollable_widget.y -= dp(SCROLL_STEP)
            case ScrollControl.HORIZONTAL:
                self.ids.scrollable_widget.x -= dp(SCROLL_STEP)
            case ScrollControl.ZOOM:
                self._zoom(ZOOM_FACTOR)
        self._apply_limits()

    def go_down(self) -> None:
        """Scroll down, right or zoom out the image based on the active control."""
        match self.active_control:
            case ScrollControl.VERTICAL:
                self.ids.scrollable_widget.y += dp(SCROLL_STEP)
            case ScrollControl.HORIZONTAL:
                self.ids.scrollable_widget.x += dp(SCROLL_STEP)
            case ScrollControl.ZOOM:
                self._zoom(1 / ZOOM_FACTOR)
        self._apply_limits()

    def _activate_vertical_scroll(self) -> None:
        self.active_control = ScrollControl.VERTICAL

    def _activate_horizontal_scroll(self) -> None:
        self.active_control = ScrollControl.HORIZONTAL

    def _activate_zoom_scroll(self) -> None:
        self.active_control = ScrollControl.ZOOM

    def get_item(self, index: int) -> Item | None:
        """Get the item at the given index."""
        match index:
            case 0:
                return ActionItem(action=self._activate_vertical_scroll)

            case 1:
                return ActionItem(action=self._activate_horizontal_scroll)

            case 2:
                return ActionItem(action=self._activate_zoom_scroll)


Builder.load_file(
    pathlib.Path(__file__).parent.joinpath('image_viewer.kv').resolve().as_posix(),
)
