"""Generic render widget registry for the GUI client."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ubo_gui_client.gui_utils import UboPageWidget

from ubo_gui_client.widgets.frame_stream import FrameStreamRenderPage
from ubo_gui_client.widgets.image_viewer import RawImageViewer
from ubo_gui_client.widgets.qr_code import QRCodeRenderPage
from ubo_gui_client.widgets.qr_code_carousel import QRCodeCarouselRenderPage
from ubo_gui_client.widgets.status import StatusRenderPage
from ubo_gui_client.widgets.text_viewer import RawTextViewer

GENERIC_RENDER_WIDGETS: dict[str, type[UboPageWidget]] = {
    'qr_code': QRCodeRenderPage,
    'qr_code_carousel': QRCodeCarouselRenderPage,
    'status': StatusRenderPage,
    'text_viewer': RawTextViewer,
    'image_viewer': RawImageViewer,
    'frame_stream': FrameStreamRenderPage,
}
