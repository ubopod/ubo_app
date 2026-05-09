"""View components for TUI."""

from __future__ import annotations

from ubo_tui.views.application import ApplicationView
from ubo_tui.views.home import HomeView
from ubo_tui.views.instruction import InstructionView
from ubo_tui.views.menu import MenuView
from ubo_tui.views.notification import NotificationView
from ubo_tui.views.prompt import PromptView
from ubo_tui.views.render import RenderView

__all__ = [
    "ApplicationView",
    "HomeView",
    "InstructionView",
    "MenuView",
    "NotificationView",
    "PromptView",
    "RenderView",
]
