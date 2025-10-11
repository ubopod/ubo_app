"""Camera settings menu pages."""

from __future__ import annotations

from ubo_gui.menu.types import ActionItem, HeadedMenu, SubMenuItem

from ubo_app.store.main import store
from ubo_app.store.services.camera import (
    CameraDetectAction,
    CameraSetIndexAction,
    CameraState,
)


@store.autorun(lambda state: state.camera)
def camera_settings_menu(state: CameraState) -> HeadedMenu:
    """Create camera selection menu with detected cameras.

    Args:
        state: Camera state from the store

    Returns:
        HeadedMenu with camera selection options

    """
    items = []

    # Add menu items for each detected camera
    for index in state.available_cameras:
        is_selected = index == state.selected_camera_index
        items.append(
            ActionItem(
                label=f'Camera {index}',
                icon='' if is_selected else '',  # noqa: RUF034
                background_color='#00ff00' if is_selected else None,
                color='#000000' if is_selected else None,
                action=lambda i=index: store.dispatch(CameraSetIndexAction(index=i)),
            ),
        )

    # Add detect cameras button
    items.append(
        ActionItem(
            label='Detect Cameras',
            icon='󰄄',
            action=lambda: store.dispatch(CameraDetectAction()),
        ),
    )

    return HeadedMenu(
        title='Camera Settings',
        heading='Select Camera Device',
        sub_heading=f'Current: Camera {state.selected_camera_index}'
        if state.available_cameras
        else 'No cameras detected',
        items=items,
        placeholder='No cameras detected. Click "Detect Cameras" to scan.'
        if not state.available_cameras
        else None,
    )


# Create the menu item for registration
CameraSettingsMenu = SubMenuItem(
    label='Camera',
    icon='',
    sub_menu=camera_settings_menu,
)
