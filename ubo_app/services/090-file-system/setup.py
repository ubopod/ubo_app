"""Setup module for initializing the File System application."""

from __future__ import annotations

from file_application import PathSelectorApplication
from ubo_gui.menu.types import ActionItem

from ubo_app.store.core.types import RegisterRegularAppAction
from ubo_app.store.main import store
from ubo_app.store.services.file_system import PathSelectorConfig


def init_service() -> None:
    """Initialize the service by registering the File System application."""
    store.dispatch(
        RegisterRegularAppAction(
            menu_item=ActionItem(
                label='File System',
                icon='󰉋',
                action=lambda: PathSelectorApplication(
                    config=PathSelectorConfig(),
                ).open(),
            ),
            key='file-system',
        ),
    )
