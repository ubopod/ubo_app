"""Provides reusable gui stuff."""

from __future__ import annotations

import uuid
from typing import Literal, TypeAlias

from ubo_gui.page import PageWidget
from ubo_gui.prompt import PromptWidget

from ubo_gui_client.constants import SUCCESS_COLOR

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
