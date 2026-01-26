"""View Renderer for the Dumb UI Architecture.

This module provides the ViewRenderer class that subscribes to ViewChangedEvent
and renders the UI based on the view data received. This is the core of the
dumb UI architecture where the UI is a pure renderer with no internal state.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from kivy.clock import mainthread

from ubo_app.constants import DEBUG_MENU, USE_DUMB_UI
from ubo_app.logger import logger
from ubo_app.store.core.types import (
    ApplicationViewData,
    HomeViewData,
    MenuItemData,
    MenuViewData,
    NotificationViewData,
    ViewChangedEvent,
)
from ubo_app.store.main import store

if TYPE_CHECKING:
    from ubo_gui.menu.menu_widget import MenuWidget

    from ubo_app.store.core.types import ViewData


def _view_to_dict(view: ViewData) -> dict:
    """Convert a ViewData to a dictionary for logging.

    Looks up additional details from the store for notifications/applications.
    """
    result: dict = {'type': view.type}

    if isinstance(view, HomeViewData):
        result['show_status_bar'] = view.show_status_bar
        result['menu_items'] = [
            _menu_item_to_dict(item) for item in view.menu_items
        ]
        result['cpu_percent'] = view.cpu_percent
        result['ram_percent'] = view.ram_percent
        result['volume_level'] = view.volume_level

    elif isinstance(view, MenuViewData):
        result['show_status_bar'] = view.show_status_bar
        result['title'] = view.title
        result['page_index'] = view.page_index
        result['total_pages'] = view.total_pages
        result['items'] = [
            _menu_item_to_dict(item) if item else None for item in view.items
        ]

    elif isinstance(view, ApplicationViewData):
        result['show_status_bar'] = view.show_status_bar
        result['application_id'] = view.application_id
        # Include extra_data (e.g., text content from NotificationInfo)
        if view.extra_data:
            result['extra_data'] = dict(view.extra_data)
        # Look up application details from registered applications
        app_info = _get_application_info(view.application_id)
        if app_info:
            result['application_info'] = app_info

    elif isinstance(view, NotificationViewData):
        result['show_status_bar'] = view.show_status_bar
        result['notification_id'] = view.notification_id
        # Look up full notification details from store
        notification_info = _get_notification_info(view.notification_id)
        if notification_info:
            result.update(notification_info)
        else:
            # Use the view's own fields if available
            result['title'] = view.title
            result['content'] = view.content
            result['icon'] = view.icon
            result['color'] = view.color

    return result


def _get_notification_info(notification_id: str) -> dict | None:
    """Look up notification details from the notifications state."""
    state = store._state  # noqa: SLF001
    if state is None:
        return None

    try:
        notifications = state.notifications.notifications
        for notification in notifications:
            if notification.id == notification_id:
                result = {
                    'title': notification.title,
                    'content': notification.content,
                    'icon': notification.icon,
                    'color': notification.color,
                    'importance': str(notification.importance),
                    'sender': notification.sender,
                    'is_read': notification.is_read,
                }
                # Include extra_information text if available
                if notification.extra_information:
                    result['extra_information'] = notification.extra_information.text
                return result
    except (AttributeError, TypeError):
        pass
    return None


def _get_application_info(application_id: str) -> dict | None:
    """Look up application details from registered applications."""
    from ubo_app.store.ubo_actions import get_registered_application

    try:
        app_class = get_registered_application(application_id)
        if app_class:
            return {
                'class_name': app_class.__name__,
                'module': app_class.__module__,
            }
    except (KeyError, AttributeError, TypeError, ValueError):
        pass
    return None


def _menu_item_to_dict(item: MenuItemData) -> dict:
    """Convert a MenuItemData to a dictionary for logging."""
    return {
        'key': item.key,
        'label': item.label,
        'icon': item.icon,
        'color': item.color,
        'is_short': item.is_short,
        'action_id': item.action_id,
    }


class ViewRenderer:
    """Renders the UI based on ViewData from Redux state.

    This class subscribes to ViewChangedEvent and updates the UI accordingly.
    It is enabled only when USE_DUMB_UI is set to True.
    """

    def __init__(self, menu_widget: MenuWidget) -> None:
        """Initialize the ViewRenderer.

        Args:
            menu_widget: The MenuWidget to render to.

        """
        self.menu_widget = menu_widget
        self._current_view_type: str | None = None

        if USE_DUMB_UI:
            self._setup_subscription()
            logger.info('[ViewRenderer] Dumb UI mode enabled')

    def _setup_subscription(self) -> None:
        """Subscribe to ViewChangedEvent."""
        store.subscribe_event(
            ViewChangedEvent,
            self._on_view_changed,
            keep_ref=False,
        )

    @mainthread
    def _on_view_changed(self, event: ViewChangedEvent) -> None:
        """Handle ViewChangedEvent by rendering the appropriate view.

        Args:
            event: The ViewChangedEvent containing the new view data.

        """
        view = event.view
        if DEBUG_MENU:
            # Log the full view data structure with looked-up details
            view_dict = _view_to_dict(view)
            logger.info(
                '[ViewRenderer] ViewChanged:\n%s',
                json.dumps(view_dict, indent=2, ensure_ascii=False),
            )

        self._render_view(view)

    def _render_view(self, view: ViewData) -> None:
        """Dispatch to the appropriate render method based on view type."""
        if isinstance(view, HomeViewData):
            self._render_home_view(view)
        elif isinstance(view, MenuViewData):
            self._render_menu_view(view)
        elif isinstance(view, ApplicationViewData):
            self._render_application_view(view)
        elif isinstance(view, NotificationViewData):
            self._render_notification_view(view)

    def _render_home_view(self, view: HomeViewData) -> None:
        """Render the home view."""
        _ = view

    def _render_menu_view(self, view: MenuViewData) -> None:
        """Render a menu view."""
        _ = view

    def _render_application_view(self, view: ApplicationViewData) -> None:
        """Render an application view."""
        _ = view

    def _render_notification_view(self, view: NotificationViewData) -> None:
        """Render a notification view."""
        _ = view
