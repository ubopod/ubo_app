"""Utility fixtures for testing ubo_app."""

from .app import AppContext, app_context
from .dispatch import Dispatcher, dispatcher
from .load_services import LoadServices, load_services
from .menu import WaitForEmptyMenu, wait_for_empty_menu, wait_for_menu_item
from .mock_camera import MockCamera, camera
from .mock_environment import mock_environment
from .snapshot import WindowSnapshot, snapshot_prefix, window_snapshot
from .stability import Stability, stability
from .store import store

__all__ = (
    'AppContext',
    'Dispatcher',
    'LoadServices',
    'MockCamera',
    'Stability',
    'WaitForEmptyMenu',
    'WindowSnapshot',
    'app_context',
    'camera',
    'dispatcher',
    'load_services',
    'mock_environment',
    'snapshot_prefix',
    'stability',
    'store',
    'wait_for_empty_menu',
    'wait_for_menu_item',
    'window_snapshot',
)
