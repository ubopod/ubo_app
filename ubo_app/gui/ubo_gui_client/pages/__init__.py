"""GUI client page widgets for application rendering.

These widgets are only loaded in the GUI client (Kivy mode),
never in headless mode. They receive data via OpenApplicationAction kwargs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ubo_gui_client.client import GUIClient
    from ubo_gui_client.gui_utils import UboPageWidget

# Local application registry for the GUI client process.
# Maps application_id -> widget class. This replaces the core's
# `ubo_app.store.ubo_actions.application_registry` which isn't
# available in the GUI client's separate venv.
application_registry: dict[str, type[UboPageWidget]] = {}


def register_application(
    *,
    application_id: str,
    application: type[UboPageWidget],
) -> None:
    """Register an application in the local GUI client registry."""
    if application_id in application_registry:
        msg = f'Application ID {application_id} is already registered.'
        raise ValueError(msg)

    application_registry[application_id] = application


def get_grpc_client() -> GUIClient:
    """Get the gRPC client from the running Kivy app."""
    from kivy.app import App

    app = App.get_running_app()
    if app is None:
        msg = 'No running Kivy app'
        raise RuntimeError(msg)
    return app.grpc_client

def register_all_pages() -> None:
    """Register all page widgets in the application registry."""
    from .camera_viewfinder import CameraViewfinderPage
    from .docker_qrcode_page import DockerQRCodePage
    from .rpi_connect_pages import RPiConnectQRCodePage, RPiConnectSignInPage
    from .vscode_pages import VSCodeLoginPage, VSCodeQRCodePage
    from .wifi_pages import WiFiConnectionPage, WiFiCreateConnectionPage

    register_application(
        application_id='vscode:qrcode-page',
        application=VSCodeQRCodePage,
    )
    register_application(
        application_id='vscode:login-page',
        application=VSCodeLoginPage,
    )
    register_application(
        application_id='rpi-connect:qrcode-page',
        application=RPiConnectQRCodePage,
    )
    register_application(
        application_id='rpi-connect:signin-page',
        application=RPiConnectSignInPage,
    )
    register_application(
        application_id='docker:qrcode-page',
        application=DockerQRCodePage,
    )
    register_application(
        application_id='wifi:connection-page',
        application=WiFiConnectionPage,
    )
    register_application(
        application_id='wifi:create-connection-page',
        application=WiFiCreateConnectionPage,
    )
    register_application(
        application_id='camera:viewfinder',
        application=CameraViewfinderPage,
    )
