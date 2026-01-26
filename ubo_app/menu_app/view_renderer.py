"""View Renderer for the Dumb UI Architecture.

This module provides the ViewRenderer class that subscribes to ViewChangedEvent
and renders the UI based on the view data received. This is the core of the
dumb UI architecture where the UI is a pure renderer with no internal state.
"""
from __future__ import annotations

import contextlib
import json
import math
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
    ProgressNotificationData,
    StatusBarData,
    StatusIconData,
    ViewChangedEvent,
)
from ubo_app.store.main import store

if TYPE_CHECKING:
    from ubo_gui.menu.menu_widget import MenuWidget

    from ubo_app.menu_app.menu_central import MenuAppCentral
    from ubo_app.store.core.types import ViewData
    from ubo_app.store.main import RootState


def compute_status_bar_data(state: RootState) -> StatusBarData:
    """Compute StatusBarData from the full Redux state.

    This consolidates all status bar information from various state slices
    into a single serializable object.
    """
    # Compute progress notifications from notifications with progress
    progress_notifications: list[ProgressNotificationData] = []
    with contextlib.suppress(AttributeError, TypeError):
        progress_notifications = [
            ProgressNotificationData(
                id=notification.id,
                progress=(
                    None
                    if math.isnan(notification.progress)
                    else notification.progress
                ),
                color=notification.color,
            )
            for notification in state.notifications.notifications
            if notification.progress is not None
        ]

    # Compute icons from status_icons state
    icons: tuple[StatusIconData, ...] = ()
    with contextlib.suppress(AttributeError, TypeError):
        icons = tuple(
            StatusIconData(symbol=icon.symbol, color=icon.color)
            for icon in state.status_icons.icons
        )

    # Get temperature and light from sensors
    temperature: float | None = None
    light_level: float | None = None
    with contextlib.suppress(AttributeError, TypeError):
        temperature = state.sensors.temperature.value
        light_level = state.sensors.light.value

    # Get system metrics (clock)
    clock = ''
    with contextlib.suppress(AttributeError, TypeError):
        clock = state.system.clock

    # Get recording states
    is_recording = False
    is_replaying = False
    is_recording_audio = False
    with contextlib.suppress(AttributeError, TypeError):
        is_recording = state.main.is_recording
        is_replaying = state.main.is_replaying
    with contextlib.suppress(AttributeError, TypeError):
        is_recording_audio = state.audio.is_recording

    return StatusBarData(
        title='',  # Title is managed by MenuWidget binding
        is_recording=is_recording,
        is_replaying=is_replaying,
        is_recording_audio=is_recording_audio,
        progress_notifications=tuple(progress_notifications),
        clock=clock,
        temperature=temperature,
        light_level=light_level,
        icons=icons,
    )


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

    def __init__(self, menu_widget: MenuWidget, app: MenuAppCentral) -> None:
        """Initialize the ViewRenderer.

        Args:
            menu_widget: The MenuWidget to render to.
            app: The MenuAppCentral instance for accessing header/footer.

        """
        self.menu_widget = menu_widget
        self.app = app
        self._current_view_type: str | None = None
        self._last_status_bar: StatusBarData | None = None

        if USE_DUMB_UI:
            self._setup_subscription()
            logger.info('[ViewRenderer] Dumb UI mode enabled')

            # Initial render after a short delay to let the app initialize
            from kivy.clock import Clock

            Clock.schedule_once(lambda _: self._initial_render(), 1.0)

    def _initial_render(self) -> None:
        """Perform initial render of status bar after app startup."""
        state = store._state  # noqa: SLF001
        if state is not None:
            status_bar = compute_status_bar_data(state)
            logger.info(
                '[ViewRenderer] Initial StatusBar render: clock=%s, temp=%s',
                status_bar.clock,
                status_bar.temperature,
            )
            self._render_status_bar(status_bar)

    def _setup_subscription(self) -> None:
        """Subscribe to ViewChangedEvent and state changes for dynamic updates."""
        store.subscribe_event(
            ViewChangedEvent,
            self._on_view_changed,
            keep_ref=False,
        )

        # Subscribe to state changes that affect the home view
        # These autoruns ensure dynamic updates without navigation
        from redux import AutorunOptions

        store.autorun(
            lambda state: (
                state.system.cpu_percent if hasattr(state, 'system') else 0.0,
                state.system.ram_percent if hasattr(state, 'system') else 0.0,
            ),
            options=AutorunOptions(keep_ref=False),
        )(self._on_system_metrics_changed)

        store.autorun(
            lambda state: state.audio.playback_volume,
            options=AutorunOptions(keep_ref=False),
        )(self._on_volume_changed)

        # Subscribe to status bar state changes
        store.autorun(
            lambda state: (
                state.system.clock if hasattr(state, 'system') else '',
                state.main.is_recording,
                state.main.is_replaying,
                state.audio.is_recording if hasattr(state, 'audio') else False,
            ),
            options=AutorunOptions(keep_ref=False),
        )(self._on_status_bar_changed)

    @mainthread
    def _on_system_metrics_changed(
        self,
        metrics: tuple[float, float],
    ) -> None:
        """Handle system metrics (CPU/RAM) state changes."""
        cpu_percent, ram_percent = metrics

        # Only update if we're on home page
        home_page = getattr(self.menu_widget, 'home_page', None)
        if home_page is None:
            return

        # Check if home page is currently visible
        if self.menu_widget.current_screen != home_page:
            return

        cpu_gauge = getattr(home_page, 'cpu_gauge', None)
        if cpu_gauge is not None:
            cpu_gauge.value = cpu_percent

        ram_gauge = getattr(home_page, 'ram_gauge', None)
        if ram_gauge is not None:
            ram_gauge.value = ram_percent

    @mainthread
    def _on_volume_changed(self, volume: float) -> None:
        """Handle volume state changes."""
        # Only update if we're on home page
        home_page = getattr(self.menu_widget, 'home_page', None)
        if home_page is None:
            return

        # Check if home page is currently visible
        if self.menu_widget.current_screen != home_page:
            return

        volume_widget = getattr(home_page, 'volume_widget', None)
        if volume_widget is not None:
            volume_widget.value = volume * 100

    @mainthread
    def _on_status_bar_changed(self, _: tuple[str, bool, bool, bool]) -> None:
        """Handle status bar state changes."""
        state = store._state  # noqa: SLF001
        if state is not None:
            status_bar = compute_status_bar_data(state)
            self._render_status_bar(status_bar)

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

        # Compute and render status bar from full state
        state = store._state  # noqa: SLF001
        if state is not None:
            status_bar = compute_status_bar_data(state)
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
        """Render the home view with CPU/RAM gauges and volume."""
        _ = view  # view.cpu_percent etc. not populated yet, read from state

        # Read values from full state
        state = store._state  # noqa: SLF001
        if state is None:
            return

        # Get home page widget
        home_page = getattr(self.menu_widget, 'home_page', None)
        if home_page is None:
            return

        # Update CPU gauge
        cpu_gauge = getattr(home_page, 'cpu_gauge', None)
        if cpu_gauge is not None:
            with contextlib.suppress(AttributeError, TypeError):
                cpu_gauge.value = state.system.cpu_percent

        # Update RAM gauge
        ram_gauge = getattr(home_page, 'ram_gauge', None)
        if ram_gauge is not None:
            with contextlib.suppress(AttributeError, TypeError):
                ram_gauge.value = state.system.ram_percent

        # Update volume widget
        volume_widget = getattr(home_page, 'volume_widget', None)
        if volume_widget is not None:
            with contextlib.suppress(AttributeError, TypeError):
                volume_widget.value = state.audio.playback_volume * 100

        if DEBUG_MENU:
            cpu = getattr(state, 'system', None)
            ram = getattr(state, 'system', None)
            vol = getattr(state, 'audio', None)
            logger.info(
                '[ViewRenderer] Home view: cpu=%.1f, ram=%.1f, vol=%.1f',
                cpu.cpu_percent if cpu else 0,
                ram.ram_percent if ram else 0,
                (vol.playback_volume if vol else 0) * 100,
            )

    def _render_menu_view(self, view: MenuViewData) -> None:
        """Render a menu view."""
        _ = view

    def _render_application_view(self, view: ApplicationViewData) -> None:
        """Render an application view."""
        _ = view

    def _render_notification_view(self, view: NotificationViewData) -> None:
        """Render a notification view."""
        _ = view

    def _render_status_bar(self, status_bar: StatusBarData) -> None:
        """Render the status bar (header and footer) from StatusBarData.

        This updates the header and footer widgets based on the computed
        StatusBarData. During the transition period (Checkpoint 1), this
        coexists with the existing autoruns that also update these widgets.
        """
        # Skip if no change (simple optimization)
        if self._last_status_bar == status_bar:
            return
        self._last_status_bar = status_bar

        if DEBUG_MENU:
            logger.info(
                '[ViewRenderer] Rendering StatusBar: clock=%s, temp=%s, '
                'recording=%s, replaying=%s, audio_recording=%s, '
                'icons=%d, progress=%d',
                status_bar.clock,
                status_bar.temperature,
                status_bar.is_recording,
                status_bar.is_replaying,
                status_bar.is_recording_audio,
                len(status_bar.icons),
                len(status_bar.progress_notifications),
            )

        # Update footer widgets
        self._render_footer(status_bar)

        # Update header widgets
        self._render_header(status_bar)

    def _render_footer(self, status_bar: StatusBarData) -> None:
        """Update footer widgets (clock, temperature, light, icons)."""
        from kivy.metrics import dp
        from kivy.uix.label import Label
        from kivy.uix.widget import Widget

        # Update clock
        if hasattr(self.app, 'clock_widget') and hasattr(self.app.clock_widget, 'text'):
            self.app.clock_widget.text = status_bar.clock

        # Update temperature
        if hasattr(self.app, 'temperature'):
            if status_bar.temperature is None:
                self.app.temperature.text = '-'
            else:
                self.app.temperature.text = f'{status_bar.temperature:0.1f}󰔄'

        # Update light level (opacity based on lux)
        if hasattr(self.app, 'light'):
            if status_bar.light_level is None:
                self.app.light.color = (0.5, 0, 0, 1)
            else:
                v = min(status_bar.light_level, 140) / 140
                self.app.light.color = (1, 1, 1, v)

        # Update status icons
        if hasattr(self.app, 'icons_layout'):
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
        if should_show:
            if sign not in self.app.header_content.children:
                sign.color = color
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
        from ubo_gui.progress_ring import ProgressRingWidget

        seen_ids: set[str] = set()

        for pn in status_bar.progress_notifications:
            seen_ids.add(pn.id)
            widget = self._get_or_create_progress_widget(pn, dp)
            if isinstance(widget, ProgressRingWidget) and pn.progress is not None:
                widget.progress = pn.progress
            widget.color = pn.color

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
        dp: object,
    ) -> object:
        """Get existing or create new progress widget for a notification."""
        from ubo_gui.progress_ring import ProgressRingWidget
        from ubo_gui.spinner import SpinnerWidget

        if pn.progress is None:
            # Indeterminate - use SpinnerWidget
            if pn.id not in self.app.notification_widgets or not isinstance(
                self.app.notification_widgets[pn.id][1],
                SpinnerWidget,
            ):
                widget = SpinnerWidget(
                    font_size=dp(16),
                    size_hint=(None, None),
                    pos_hint={'center_y': 0.5},
                    height=dp(16),
                    width=dp(16),
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
                height=dp(16),
                band_width=dp(7),
                size_hint=(None, None),
                pos_hint={'center_y': 0.5},
            )
            self.app.notification_widgets[pn.id] = (None, widget)
        return self.app.notification_widgets[pn.id][1]
