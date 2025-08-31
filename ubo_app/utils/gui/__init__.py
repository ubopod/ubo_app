"""Provides reusable gui stuff."""

from __future__ import annotations

import pathlib
import uuid
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, TypeAlias

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
from ubo_gui.page import PageWidget
from ubo_gui.prompt import PromptWidget
from ubo_gui.utils import mainthread_if_needed

from ubo_app.colors import SUCCESS_COLOR
from ubo_app.constants import HEIGHT, WIDTH

if TYPE_CHECKING:
    from kivy.uix.widget import Widget

ZOOM_FACTOR = 1.1
SCROLL_STEP = 10
ItemParameters: TypeAlias = dict[Literal['background_color', 'color', 'icon'], str]

SELECTED_ITEM_PARAMETERS: ItemParameters = {
    'background_color': SUCCESS_COLOR,
    'icon': '󰱒',
}
UNSELECTED_ITEM_PARAMETERS: ItemParameters = {
    'icon': '󰄱',
}


class UboPageWidget(PageWidget):
    """Base class for all UBO pages."""

    id: str

    def __init__(self, **kwargs: object) -> None:
        """Initialize the UBO page widget."""
        self.id = uuid.uuid4().hex
        kwargs = {**kwargs}
        items = kwargs.pop('items', None)
        if items is not None and not isinstance(items, list):
            msg = 'items must be a list'
            raise TypeError(msg)
        super().__init__(items=items, **kwargs)


class UboPromptWidget(PromptWidget, UboPageWidget):
    """Base class for all UBO prompts."""


class RawTextViewer(UboPageWidget):
    """Kivy widget for displaying text in a scrollable view."""

    text: str = StringProperty()

    def go_up(self) -> None:
        """Scroll up the error report."""
        self.ids.scrollable_widget.y = max(
            self.ids.scrollable_widget.y - dp(100),
            self.ids.container.y
            - (self.ids.scrollable_widget.height - self.ids.container.height),
        )

    def go_down(self) -> None:
        """Scroll down the error report."""
        self.ids.scrollable_widget.y = min(
            self.ids.scrollable_widget.y + dp(100),
            self.ids.container.y,
        )


class ScrollControl(StrEnum):
    """Enum for scroll control."""

    VERTICAL = 'vertical_scroll'
    HORIZONTAL = 'horizontal_scroll'
    ZOOM = 'zoom_scroll'


class RawImageViewer(UboPageWidget):
    """Kivy widget for displaying raw image."""

    def _get_texture(self) -> None:
        """Update the image when the image property changes."""
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
    pathlib.Path(__file__).parent.joinpath('raw_text_viewer.kv').resolve().as_posix(),
)
Builder.load_file(
    pathlib.Path(__file__).parent.joinpath('raw_image_viewer.kv').resolve().as_posix(),
)
