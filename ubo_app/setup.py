"""Compatibility layer for different environments (Kivy GUI mode)."""

from __future__ import annotations

from ubo_app.setup_headless import (
    clear_signal_handlers,
    signal_handler,
)

__all__ = ['clear_signal_handlers', 'setup', 'signal_handler']


def setup() -> None:
    """Set up for Kivy GUI environments (extends headless setup)."""
    from ubo_app.setup_headless import setup_headless

    setup_headless()

    from ubo_gui import setup as setup_ubo_gui

    import ubo_app.display as _  # noqa: F401

    setup_ubo_gui()

    from ubo_app.store.ubo_actions import register_application
    from ubo_app.utils.gui import RawImageViewer, RawTextViewer

    register_application(
        application=RawTextViewer,
        application_id='ubo:raw-text-viewer',
    )
    register_application(
        application=RawImageViewer,
        application_id='ubo:raw-image-viewer',
    )
