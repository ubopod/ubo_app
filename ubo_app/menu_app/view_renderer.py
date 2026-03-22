"""View Renderer for the Dumb UI Architecture.

This module provides the ViewRenderer class that uses autoruns on
``state.main.current_view`` and ``state.main.status_bar`` to reactively
render the UI.  The state is already computed and stored by the autoruns
in ``view_computation.py``; this class simply watches those slices and
renders when they change.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from kivy.clock import mainthread

from ubo_app.constants import DEBUG_MENU
from ubo_app.logger import logger
from ubo_app.store.core.constants import PAGE_SIZE
from ubo_app.store.core.types import (
    ApplicationViewData,
    HomeViewData,
    MenuItemData,
    MenuViewData,
    NotificationViewData,
    StatusBarData,
)
from ubo_app.store.main import store

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from kivy.uix.widget import Widget
    from ubo_gui.menu.menu_widget import MenuWidget

    from ubo_app.menu_app.menu_central import MenuAppCentral
    from ubo_app.store.core.types import ViewData
    from ubo_app.store.core.types.status_bar import ProgressNotificationData
    from ubo_app.store.services.notifications import Notification


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


@store.with_state(lambda state: state.notifications.notifications)
def _get_notification_info(
    notifications: Sequence[Notification],
    notification_id: str,
) -> dict | None:
    """Look up notification details from the notifications state."""
    try:
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

    Uses autoruns on ``state.main.current_view`` and
    ``state.main.status_bar`` to reactively update the UI when state changes.
    """

    def __init__(self, menu_widget: MenuWidget, app: MenuAppCentral) -> None:
        """Initialize the ViewRenderer.

        Args:
            menu_widget: The MenuWidget to render to.
            app: The MenuAppCentral instance for accessing header/footer.

        """
        self.menu_widget = menu_widget
        self.app = app
        self._view_changed_count: int = 0

        self._setup_autoruns()
        logger.info('[ViewRenderer] Initialized')

        # Schedule a deferred re-render so the status bar is populated even if
        # the first autorun fires before build() creates header/footer widgets.
        from kivy.clock import Clock

        Clock.schedule_once(lambda _: self._retry_initial_render(), 1.0)

    def _setup_autoruns(self) -> None:
        """Set up autoruns that watch computed state and render the UI."""
        from redux import AutorunOptions

        # -- View autorun: watches state.main.current_view -----------------
        store.autorun(
            lambda state: state.main.current_view,
            options=AutorunOptions(keep_ref=False),
        )(self._on_view_changed)

        # -- Status bar autorun: watches state.main.status_bar -------------
        store.autorun(
            lambda state: state.main.status_bar,
            options=AutorunOptions(keep_ref=False),
        )(self._on_status_bar_changed)


    def _retry_initial_render(self) -> None:
        """Re-trigger status bar render after build() has created widgets."""

        @store.with_state(lambda state: state.main.status_bar)
        def _render_once(status_bar: StatusBarData | None) -> None:
            if status_bar is not None:
                self._render_status_bar(status_bar)

        _render_once()

    @mainthread
    def _on_view_changed(self, view: ViewData | None) -> None:
        """Handle current_view state changes."""
        if view is None:
            return

        self._view_changed_count += 1

        if DEBUG_MENU:
            # Log the full view data structure with looked-up details
            view_dict = _view_to_dict(view)
            logger.info(
                '[ViewRenderer] ViewChanged #%d:\n%s',
                self._view_changed_count,
                json.dumps(view_dict, indent=2, ensure_ascii=False),
            )

        self._render_view(view)

    @mainthread
    def _on_status_bar_changed(self, status_bar: StatusBarData | None) -> None:
        """Handle status_bar state changes."""
        if status_bar is None:
            return
        self._render_status_bar(status_bar)

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
        """Render the home view (gauges/volume owned by HomePage autoruns)."""
        if DEBUG_MENU:
            logger.info(
                '[ViewRenderer] Home view: cpu=%.1f, ram=%.1f, vol=%.1f',
                view.cpu_percent,
                view.ram_percent,
                view.volume_level * 100,
            )

    def _render_menu_view(self, view: MenuViewData) -> None:
        """Render a menu view with title, items, and pagination."""
        if DEBUG_MENU:
            # Show items for current page
            start = view.page_index * PAGE_SIZE
            end = start + PAGE_SIZE
            page_items = view.items[start:end] if view.items else ()
            item_labels = [
                item.label if item else '<empty>' for item in page_items
            ]
            logger.info(
                '[ViewRenderer] Menu view: title=%s, page=%d/%d, items=%s',
                view.title,
                view.page_index + 1,
                view.total_pages,
                item_labels,
            )

        # Verify title matches (MenuWidget has its own title binding)
        current_title = getattr(self.menu_widget, 'title', None)
        if current_title and current_title != view.title and DEBUG_MENU:
            logger.warning(
                '[ViewRenderer] Title mismatch: widget=%s, view=%s',
                current_title,
                view.title,
            )

        # Verify page index matches
        current_page = getattr(self.menu_widget, 'page_index', None)
        if current_page is not None and current_page != view.page_index and DEBUG_MENU:
            logger.warning(
                '[ViewRenderer] Page index mismatch: widget=%d, view=%d',
                current_page,
                view.page_index,
            )

    def _render_application_view(self, view: ApplicationViewData) -> None:
        """Render an application view."""
        if DEBUG_MENU:
            logger.info(
                '[ViewRenderer] Application view: id=%s, extra_data=%s',
                view.application_id,
                view.extra_data if view.extra_data else '{}',
            )

    def _render_notification_view(self, view: NotificationViewData) -> None:
        """Render a notification view."""
        if DEBUG_MENU:
            logger.info(
                '[ViewRenderer] Notification view: id=%s, title=%s',
                view.notification_id,
                view.title,
            )

    def _render_status_bar(self, status_bar: StatusBarData) -> None:
        """Render the status bar (header and footer) from StatusBarData."""
        if DEBUG_MENU:
            logger.info(
                '[ViewRenderer] Rendering StatusBar: clock=%s, icons=%d, progress=%d',
                status_bar.clock,
                len(status_bar.icons),
                len(status_bar.progress_notifications),
            )

        # Update title from StatusBarData (hostname on home view)
        title = status_bar.title or ''
        if title and hasattr(self.app, 'root') and self.app.root is not None:
            self.app.root.title = title

        # Update footer widgets
        self._render_footer(status_bar)

        # Update header widgets
        self._render_header(status_bar)

    def _render_footer(self, status_bar: StatusBarData) -> None:
        """Update footer widgets (clock, temperature, light, icons)."""
        from kivy.metrics import dp
        from kivy.uix.label import Label
        from kivy.uix.widget import Widget

        # Update clock (only if state has a value, otherwise let the widget self-update)
        if (
            hasattr(self.app, 'clock_widget')
            and hasattr(self.app.clock_widget, 'text')
            and status_bar.clock
        ):
            self.app.clock_widget.text = status_bar.clock

        # Update temperature
        if hasattr(self.app, 'temperature'):
            if status_bar.temperature is None:
                self.app.temperature.text = ''
            else:
                self.app.temperature.text = f'{status_bar.temperature:0.1f}󰔄'

        # Update light level (opacity based on lux)
        if hasattr(self.app, 'light'):
            if status_bar.light_level is None:
                # No sensor data - show full white
                self.app.light.color = (1, 1, 1, 1)
            else:
                v = min(status_bar.light_level, 140) / 140
                self.app.light.color = (1, 1, 1, v)

        # Update status icons
        if not hasattr(self.app, 'icons_layout'):
            return
        self.app.icons_layout.clear_widgets()
        for icon_data in list(reversed(status_bar.icons))[:4]:
            label = Label(
                text=icon_data.symbol,
                color=icon_data.color,
                font_size=dp(20),
                font_features='fill=0',
                size_hint=(None, 1),
                width=dp(22),
                markup=True,
            )
            self.app.icons_layout.add_widget(label)
        self.app.icons_layout.add_widget(
            Widget(size_hint=(None, 1), width=dp(2)),
        )
        # Ensure layout width expands to fit all icons
        self.app.icons_layout.bind(
            minimum_width=self.app.icons_layout.setter('width'),
        )

    def _render_header(self, status_bar: StatusBarData) -> None:
        """Update header widgets (recording indicators, progress notifications)."""
        self._render_recording_indicators(status_bar)
        self._render_progress_notifications(status_bar)

    def _render_recording_indicators(self, status_bar: StatusBarData) -> None:
        """Update recording and replaying indicator widgets."""
        if not hasattr(self.app, 'header_content'):
            return

        # Update recording indicator
        if hasattr(self.app, 'recording_sign'):
            self._update_sign_widget(
                sign=self.app.recording_sign,
                should_show=status_bar.is_recording or status_bar.is_recording_audio,
                color=(0, 0, 1, 1) if status_bar.is_recording else (0, 1, 0, 1),
            )

        # Update replaying indicator
        if hasattr(self.app, 'replaying_sign'):
            self._update_sign_widget(
                sign=self.app.replaying_sign,
                should_show=status_bar.is_replaying,
                color=(0, 1, 0, 1),
            )

    def _update_sign_widget(
        self,
        sign: object,
        should_show: bool,  # noqa: FBT001
        color: tuple[int, int, int, int],
    ) -> None:
        """Update a sign widget (recording or replaying indicator)."""
        from kivy.uix.widget import Widget

        if not isinstance(sign, Widget):
            return
        if should_show:
            if sign not in self.app.header_content.children:
                sign.color = color  # type: ignore[attr-defined]
                self.app.header_content.add_widget(sign)
                if hasattr(self.app, 'sign_animation'):
                    self.app.sign_animation.start(sign)
        elif sign in self.app.header_content.children:
            self.app.header_content.remove_widget(sign)
            if hasattr(self.app, 'sign_animation'):
                self.app.sign_animation.cancel(sign)

    def _render_progress_notifications(self, status_bar: StatusBarData) -> None:
        """Update progress notification widgets in the header."""
        if not hasattr(self.app, 'progress_layout'):
            return
        if not hasattr(self.app, 'notification_widgets'):
            return

        from kivy.metrics import dp
        from kivy.uix.widget import Widget
        from ubo_gui.progress_ring import ProgressRingWidget

        seen_ids: set[str] = set()

        for pn in status_bar.progress_notifications:
            seen_ids.add(pn.id)
            widget = self._get_or_create_progress_widget(pn, dp)
            if isinstance(widget, ProgressRingWidget) and pn.progress is not None:
                widget.progress = pn.progress
            if isinstance(widget, Widget):
                widget.color = pn.color  # type: ignore[attr-defined]

        # Remove old notifications
        for id_ in set(self.app.notification_widgets) - seen_ids:
            del self.app.notification_widgets[id_]

        # Rebuild progress layout
        self.app.progress_layout.clear_widgets()
        for _, widget in self.app.notification_widgets.values():
            self.app.progress_layout.add_widget(widget)
        self.app.progress_layout.width = self.app.progress_layout.minimum_width

    def _get_or_create_progress_widget(
        self,
        pn: ProgressNotificationData,
        dp_func: Callable[[float], float],
    ) -> Widget:
        """Get existing or create new progress widget for a notification."""
        from ubo_gui.progress_ring import ProgressRingWidget
        from ubo_gui.spinner import SpinnerWidget

        if pn.progress is None:
            # Indeterminate - use SpinnerWidget
            if pn.id not in self.app.notification_widgets or not isinstance(
                self.app.notification_widgets[pn.id][1],
                SpinnerWidget,
            ):
                widget: Widget = SpinnerWidget(
                    font_size=dp_func(16),
                    size_hint=(None, None),
                    pos_hint={'center_y': 0.5},
                    height=dp_func(16),
                    width=dp_func(16),
                )
                self.app.notification_widgets[pn.id] = (None, widget)
            return self.app.notification_widgets[pn.id][1]

        # Determinate - use ProgressRingWidget
        if pn.id not in self.app.notification_widgets or not isinstance(
            self.app.notification_widgets[pn.id][1],
            ProgressRingWidget,
        ):
            widget = ProgressRingWidget(
                background_color=(0.3, 0.3, 0.3, 1),
                height=dp_func(16),
                band_width=dp_func(7),
                size_hint=(None, None),
                pos_hint={'center_y': 0.5},
            )
            self.app.notification_widgets[pn.id] = (None, widget)
        return self.app.notification_widgets[pn.id][1]
