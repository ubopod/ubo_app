"""View Renderer for the Dumb UI Architecture.

This module provides the ViewRenderer class that subscribes to gRPC state
changes and renders the UI based on the view data received. The GUI is a pure
renderer with no internal state - all computation happens in the core.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from kivy.clock import mainthread
from ubo_gui.menu.types import ActionItem, HeadlessMenu

from ubo_gui_client.constants import DEBUG_MENU

if TYPE_CHECKING:
    from collections.abc import Callable

    from kivy.uix.widget import Widget
    from ubo_bindings.ubo.v1 import (
        HomeViewData,
        MenuViewData,
        StatusBarData,
        ViewData,
    )

    from ubo_gui_client.client import GUIClient
    from ubo_gui_client.menu_central import MenuWidgetWithHomePage

logger = logging.getLogger(__name__)

ViewType = Literal['home', 'menu', 'notification', 'application']


def _noop() -> None:
    """No-op action for menu items; real selection goes via gRPC."""


class ViewRenderer:
    """Renders the UI based on ViewData from gRPC state subscription.

    This class subscribes to view changes via gRPC and updates the UI
    accordingly. It is a stateless renderer — each render call resets
    to a known state before applying the new view. All state computation
    happens in the core process.
    """

    def __init__(
        self,
        menu_widget: MenuWidgetWithHomePage,
        app: object,
        client: GUIClient,
    ) -> None:
        """Initialize the ViewRenderer.

        Args:
            menu_widget: The MenuWidget to render to.
            app: The app instance for accessing header/footer widgets.
            client: The GUIClient for gRPC communication.

        """
        self.menu_widget = menu_widget
        self.app = app
        self.client = client
        self._last_status_bar: StatusBarData | None = None
        self._last_view: ViewData | None = None
        self._view_changed_count: int = 0
        self._last_home_item_keys: tuple[str, ...] = ()
        # Track the current view type so _render_menu_view knows whether
        # to push (home→menu) or replace (menu→menu).
        self._current_view_type: ViewType | None = None

        # Ensure a root menu always exists so that non-home views arriving
        # first (e.g. on reconnect to a core already in a submenu) get
        # pushed to depth 2 instead of being set as root at depth 1, which
        # would render the home page with gauges underneath.
        if not self.menu_widget.stack:
            self.menu_widget.set_root_menu(HeadlessMenu(title='', items=[]))

        self._setup_subscription()
        logger.info('[ViewRenderer] Initialized with gRPC client')

    def _reset_state(self) -> None:
        """Reset renderer state so the next view update is treated as fresh.

        Called on gRPC reconnection so the GUI fully resyncs with the core.
        """
        self._last_view = None
        self._last_status_bar = None
        self._last_home_item_keys = ()
        self._current_view_type = None
        self.menu_widget.reset_to_root()
        logger.info('[ViewRenderer] State reset for reconnection')

    def _setup_subscription(self) -> None:
        """Subscribe to view and status bar changes via gRPC."""
        self.client.subscribe_view_changes(
            self._on_state_update,
            on_reconnect=self._reset_state,
            on_disconnect=self._on_disconnect,
            on_connected=self._on_connected,
        )

    def _on_disconnect(self, delay: float, attempt: int, max_retries: int) -> None:
        """Show the disconnect overlay when the connection drops."""
        if hasattr(self.app, 'show_disconnect_overlay'):
            self.app.show_disconnect_overlay(delay, attempt, max_retries)

    def _on_connected(self) -> None:
        """Hide the disconnect overlay when the connection is restored."""
        if hasattr(self.app, 'hide_disconnect_overlay'):
            self.app.hide_disconnect_overlay()

    @mainthread
    def _on_state_update(
        self,
        view_data: ViewData,
        status_bar: StatusBarData | None,
    ) -> None:
        """Handle state updates from gRPC subscription."""
        self._view_changed_count += 1
        transition_end = getattr(
            self.menu_widget, '_running_transition_end_time', None,
        )
        queue_len = len(getattr(self.menu_widget, 'transition_queue', []))
        logger.info(
            '[ViewRenderer] State update #%d: %s (transition_end=%s, queue=%d)',
            self._view_changed_count,
            type(view_data).__name__,
            f'{transition_end - __import__("time").time():.1f}s'
            if transition_end
            else 'None',
            queue_len,
        )

        # Skip duplicate views
        if self._last_view == view_data:
            logger.info(
                '[ViewRenderer] Skipping duplicate %s #%d',
                type(view_data).__name__,
                self._view_changed_count,
            )
        else:
            self._last_view = view_data
            try:
                self._render_view(view_data)
            except Exception:
                logger.exception(
                    '[ViewRenderer] CRASH in _render_view #%d for %s',
                    self._view_changed_count,
                    type(view_data).__name__,
                )

        if status_bar is not None:
            try:
                self._render_status_bar(status_bar)
            except Exception:
                logger.exception(
                    '[ViewRenderer] CRASH in _render_status_bar #%d',
                    self._view_changed_count,
                )

    def _render_view(self, view: ViewData) -> None:
        """Dispatch to the appropriate render method based on view type."""
        from ubo_bindings.ubo.v1 import (
            ApplicationViewData as ProtoApplicationViewData,
        )
        from ubo_bindings.ubo.v1 import (
            HomeViewData as ProtoHomeViewData,
        )
        from ubo_bindings.ubo.v1 import (
            MenuViewData as ProtoMenuViewData,
        )
        from ubo_bindings.ubo.v1 import (
            NotificationViewData as ProtoNotificationViewData,
        )

        view_type = type(view).__name__
        logger.info(
            '[ViewRenderer] Rendering %s (#%d, prev=%s, depth=%d, app=%s)',
            view_type,
            self._view_changed_count,
            self._current_view_type,
            self.menu_widget.depth,
            type(self.menu_widget.current_application).__name__
            if self.menu_widget.current_application
            else 'None',
        )

        if isinstance(view, ProtoHomeViewData):
            self._render_home_view(view)
        elif isinstance(view, ProtoMenuViewData):
            self._render_menu_view(view)
        elif isinstance(view, ProtoApplicationViewData):
            self._render_application_view(view)
        elif isinstance(view, ProtoNotificationViewData):
            self._render_notification_view(view)
        else:
            logger.warning(
                '[ViewRenderer] Unknown view type: %s (#%d)',
                view_type,
                self._view_changed_count,
            )

    def _render_home_view(self, view: HomeViewData) -> None:
        """Render the home view with CPU/RAM gauges and volume.

        Resets to root and sets the root menu items from the home view data.
        """
        logger.debug(
            '[ViewRenderer] _render_home_view: resetting to root (depth=%d)',
            self.menu_widget.depth,
        )
        did_reset = self.menu_widget.reset_to_root()
        logger.debug(
            '[ViewRenderer] _render_home_view: reset_to_root returned %s, depth now=%d',
            did_reset,
            self.menu_widget.depth,
        )
        self._current_view_type = 'home'

        # Restore hostname title from cached status bar when returning to home.
        # _render_status_bar skips duplicate data, so the title won't be re-set
        # unless we do it here.
        if self._last_status_bar is not None:
            title = getattr(self._last_status_bar, 'title', '') or ''
            if title and hasattr(self.app, 'root') and self.app.root is not None:
                self.app.root.title = title

        # Convert home view menu items to root menu (only when items change)
        menu_items_wrapper = getattr(view, 'menu_items', None)
        raw_items: list[object] = []
        if menu_items_wrapper is not None:
            raw_items = getattr(menu_items_wrapper, 'items', []) or []
            item_keys = tuple(
                getattr(item, 'key', '') for item in raw_items
            )
            if item_keys != self._last_home_item_keys:
                self._last_home_item_keys = item_keys
                items = self._convert_home_items(raw_items)
                if items:
                    menu = HeadlessMenu(title='', items=items)
                    self.menu_widget.set_root_menu(menu)

        # Update gauges on home page
        home_page = getattr(self.menu_widget, 'home_page', None)
        if home_page is None:
            return

        cpu_gauge = getattr(home_page, 'cpu_gauge', None)
        if cpu_gauge is not None:
            cpu_gauge.value = getattr(view, 'cpu_percent', 0.0) or 0.0

        ram_gauge = getattr(home_page, 'ram_gauge', None)
        if ram_gauge is not None:
            ram_gauge.value = getattr(view, 'ram_percent', 0.0) or 0.0

        volume_widget = getattr(home_page, 'volume_widget', None)
        vol = getattr(view, 'volume_level', None)
        if volume_widget is not None and vol is not None:
            volume_widget.value = vol * 100

        logger.debug(
            '[ViewRenderer] Home view done: cpu=%.1f, ram=%.1f, vol=%s, items=%d',
            getattr(view, 'cpu_percent', 0.0) or 0.0,
            getattr(view, 'ram_percent', 0.0) or 0.0,
            f'{vol * 100:.0f}%' if vol is not None else 'N/A',
            len(raw_items) if menu_items_wrapper else 0,
        )

    def _render_menu_view(self, view: MenuViewData) -> None:
        """Render a menu view with title, items, and pagination.

        Converts proto items to ubo_gui ActionItems and drives the MenuWidget.
        """
        title = getattr(view, 'title', '') or ''
        items = self._convert_view_items(view)
        heading = getattr(view, 'heading', None)
        sub_heading = getattr(view, 'sub_heading', None)
        if heading:
            from ubo_gui.menu.types import HeadedMenu

            menu = HeadedMenu(
                title=title,
                heading=heading,
                sub_heading=sub_heading or '',
                items=items,
            )
        else:
            menu = HeadlessMenu(title=title, items=items)
        page_index = getattr(view, 'page_index', None)

        if self._current_view_type == 'menu':
            # Already showing a menu — replace content in-place.
            logger.info(
                '[ViewRenderer] Menu: replace in-place (depth=%d, title=%s, page=%s)',
                self.menu_widget.depth,
                title,
                page_index,
            )
            self.menu_widget.replace_top_menu(menu, page_index=page_index)
        elif self._current_view_type == 'home':
            # Coming from home — push with slide animation
            logger.info(
                '[ViewRenderer] Menu: push from home (depth=%d, title=%s)',
                self.menu_widget.depth,
                title,
            )
            self.menu_widget.push_menu(menu)
        else:
            # Coming from notification/application/startup — instant swap
            # Uses replace_top_with_menu which handles both depth 1 (push)
            # and depth 2+ (single-transition swap) without flashing home.
            logger.info(
                '[ViewRenderer] Menu: swap from %s (depth=%d, title=%s)',
                self._current_view_type,
                self.menu_widget.depth,
                title,
            )
            self.menu_widget.replace_top_with_menu(menu)

        self._current_view_type = 'menu'

        # Update page index for push/root cases
        if page_index is not None:
            self.menu_widget.page_index = page_index

        logger.debug(
            '[ViewRenderer] Menu done: title=%s, page=%d/%d, items=%d, depth=%d',
            title,
            (page_index or 0) + 1,
            getattr(view, 'total_pages', 1) or 1,
            len(items),
            self.menu_widget.depth,
        )

    def _render_application_view(self, view: object) -> None:
        """Render an application view by opening the registered widget."""
        application_id = getattr(view, 'application_id', None)

        from ubo_gui_client.pages import application_registry

        if not application_id:
            logger.warning('[ViewRenderer] Application view with no application_id')
            return

        app_class = application_registry.get(application_id)
        if app_class is None:
            logger.warning(
                '[ViewRenderer] No registered widget for application_id=%s',
                application_id,
            )
            return

        # Get extra_data kwargs for the widget
        extra_data_obj = getattr(view, 'extra_data', None)
        kwargs: dict[str, object] = {}
        if extra_data_obj is not None:
            items_dict = getattr(extra_data_obj, 'items', None)
            if isinstance(items_dict, dict):
                kwargs = dict(items_dict)

        widget = app_class(**kwargs)

        logger.info(
            '[ViewRenderer] Application: from %s (depth=%d, id=%s)',
            self._current_view_type,
            self.menu_widget.depth,
            application_id,
        )
        self.menu_widget.replace_top_with_application(widget)
        self._current_view_type = 'application'

    def _render_notification_view(self, view: object) -> None:
        """Render a notification view by opening a NotificationWidget."""
        from ubo_gui.page import PAGE_MAX_ITEMS

        from ubo_gui_client.menu_notification_handler import UboNotificationWidget

        notification_id = getattr(view, 'notification_id', '') or ''
        title = getattr(view, 'title', '') or ''
        content = getattr(view, 'content', '') or ''
        icon = getattr(view, 'icon', '') or ''
        color = getattr(view, 'color', '') or '#ffffff'

        logger.info(
            '[ViewRenderer] Notification: id=%s, title=%s, depth=%d',
            notification_id,
            title,
            self.menu_widget.depth,
        )

        # Check if this notification is already displayed at top of stack
        from ubo_gui.menu.stack_item import StackApplicationItem

        if self.menu_widget.stack:
            top = self.menu_widget.stack[-1]
            if (
                isinstance(top, StackApplicationItem)
                and isinstance(top.application, UboNotificationWidget)
                and top.application.notification_id == notification_id
            ):
                # Already displayed, just update it
                logger.debug(
                    '[ViewRenderer] Notification: updating existing widget for %s',
                    notification_id,
                )
                self._apply_notification_data(top.application, view)
                self._current_view_type = 'notification'
                return

        # Build the notification widget
        notification_widget = UboNotificationWidget(
            notification_id=notification_id,
            items=[None] * PAGE_MAX_ITEMS,
        )

        notification_widget.notification_title = title
        notification_widget.content = content
        notification_widget.icon = icon
        notification_widget.color = color
        notification_widget.title = ' '

        self._apply_notification_data(notification_widget, view)

        logger.info(
            '[ViewRenderer] Notification: opening from %s (depth=%d)',
            self._current_view_type,
            self.menu_widget.depth,
        )
        self.menu_widget.replace_top_with_application(notification_widget)
        self._current_view_type = 'notification'
        logger.info(
            '[ViewRenderer] Notification: opened widget for %s',
            notification_id,
        )

    def _apply_notification_data(
        self,
        widget: object,
        view: object,
    ) -> None:
        """Apply notification view data to a widget (create or update)."""
        from ubo_gui.menu.types import ActionItem
        from ubo_gui.page import PAGE_MAX_ITEMS

        from ubo_gui_client.constants import INFO_COLOR
        from ubo_gui_client.notification_info import NotificationInfo

        title = getattr(view, 'title', '') or ''
        content = getattr(view, 'content', '') or ''
        icon = getattr(view, 'icon', '') or ''
        color = getattr(view, 'color', '') or '#ffffff'
        extra_information = getattr(view, 'extra_information', '') or ''

        if hasattr(widget, 'notification_title'):
            widget.notification_title = title
        if hasattr(widget, 'content'):
            widget.content = content
        if hasattr(widget, 'icon'):
            widget.icon = icon
        if hasattr(widget, 'color'):
            widget.color = color

        # Build action items from the view's items
        items: list[object] = []
        items_wrapper = getattr(view, 'items', None)
        raw_items: list[object] = []
        if items_wrapper is not None:
            raw_items = getattr(items_wrapper, 'items', []) or []

        for wrapper_item in raw_items:
            item_data = getattr(wrapper_item, 'items', None)
            if item_data is None:
                items.append(None)
                continue

            action_id = getattr(item_data, 'action_id', None) or ''
            item_icon = getattr(item_data, 'icon', '') or ''
            item_label = getattr(item_data, 'label', '') or ''
            item_color = getattr(item_data, 'color', '') or ''
            item_bg = getattr(item_data, 'background_color', None)
            item_is_short = getattr(item_data, 'is_short', False) or False

            if action_id.startswith('notification:extra_info:'):
                def make_info_action(
                    renderer: ViewRenderer,
                    text: str,
                    i_icon: str,
                    i_label: str,
                    i_short: bool,
                    i_bg: str | None,
                    i_color: str,
                ) -> ActionItem:
                    def open_info() -> None:
                        info_widget = NotificationInfo(text=text)
                        renderer.menu_widget.open_application(info_widget)

                    return ActionItem(
                        key='info',
                        icon=i_icon,
                        label=i_label,
                        action=open_info,
                        is_short=i_short,
                        background_color=i_bg or INFO_COLOR,
                        color=i_color,
                    )

                items.append(
                    make_info_action(
                        self,
                        extra_information,
                        item_icon,
                        item_label,
                        item_is_short,
                        item_bg,
                        item_color,
                    ),
                )
            else:
                # Non-info notification actions (dismiss, custom) are handled
                # by the core via gRPC when the keypad event is dispatched.
                # The local action is a no-op to avoid double-dispatch.
                action_kwargs: dict = {
                    'key': getattr(item_data, 'key', '') or '',
                    'icon': item_icon,
                    'label': item_label,
                    'action': _noop,
                    'is_short': item_is_short,
                }
                if item_bg:
                    action_kwargs['background_color'] = item_bg
                if item_color:
                    action_kwargs['color'] = item_color
                items.append(ActionItem(**action_kwargs))

        if items and hasattr(widget, 'items'):
            padded_items = [None] * (PAGE_MAX_ITEMS - len(items)) + items
            widget.items = padded_items

    def _convert_view_items(self, view: MenuViewData) -> list[ActionItem]:
        """Convert MenuViewData items to ubo_gui ActionItem objects."""
        result: list[ActionItem] = []
        items_wrapper = getattr(view, 'items', None)
        if items_wrapper is None:
            return result

        # MenuViewDataItems.items is list[MenuViewDataItemsItem]
        raw_items = getattr(items_wrapper, 'items', []) or []

        for wrapper_item in raw_items:
            # Each MenuViewDataItemsItem has an 'items' field (MenuItemData)
            item_data = getattr(wrapper_item, 'items', None)
            if item_data is None:
                continue

            label = getattr(item_data, 'label', '') or ''
            icon = getattr(item_data, 'icon', None)
            color = getattr(item_data, 'color', None) or (1, 1, 1, 1)
            background_color = getattr(item_data, 'background_color', None)
            is_short = getattr(item_data, 'is_short', False) or False

            kwargs: dict = {
                'label': label,
                'icon': icon,
                'is_short': is_short,
                'action': _noop,
            }
            if color:
                kwargs['color'] = color
            if background_color:
                kwargs['background_color'] = background_color

            result.append(ActionItem(**kwargs))

        return result

    def _convert_home_items(self, raw_items: list[object]) -> list[ActionItem]:
        """Convert HomeViewData MenuItemData items to ubo_gui ActionItem objects."""
        result: list[ActionItem] = []
        for item_data in raw_items:
            label = getattr(item_data, 'label', '') or ''
            icon = getattr(item_data, 'icon', None)
            color = getattr(item_data, 'color', None) or (1, 1, 1, 1)
            background_color = getattr(item_data, 'background_color', None)
            is_short = getattr(item_data, 'is_short', False) or False

            kwargs: dict = {
                'label': label,
                'icon': icon,
                'is_short': is_short,
                'action': _noop,
            }
            if color:
                kwargs['color'] = color
            if background_color:
                kwargs['background_color'] = background_color

            result.append(ActionItem(**kwargs))

        return result

    def _render_status_bar(self, status_bar: StatusBarData) -> None:
        """Render the status bar (header and footer) from StatusBarData."""
        if self._last_status_bar == status_bar:
            return
        self._last_status_bar = status_bar

        if DEBUG_MENU:
            icons = getattr(status_bar.icons, 'items', []) or []
            progress = (
                getattr(status_bar.progress_notifications, 'items', []) or []
            )
            logger.debug(
                '[ViewRenderer] StatusBar: clock=%s, icons=%d, progress=%d',
                status_bar.clock,
                len(icons),
                len(progress),
            )

        # Update title from status bar only on the home page.
        # On menu pages, the MenuWidget manages its own title via
        # handle_title_change. Setting it here would race and overwrite
        # the menu-specific title (e.g., "Notifications (0)") with the
        # hostname.
        title = getattr(status_bar, 'title', '') or ''
        if (
            title
            and self._current_view_type in ('home', None)
            and hasattr(self.app, 'root')
            and self.app.root is not None
        ):
            self.app.root.title = title

        self._render_footer(status_bar)
        self._render_header(status_bar)

    def _render_footer(self, status_bar: StatusBarData) -> None:
        """Update footer widgets (clock, temperature, light, icons)."""
        from kivy.metrics import dp
        from kivy.uix.label import Label
        from kivy.uix.widget import Widget

        if (
            hasattr(self.app, 'clock_widget')
            and hasattr(self.app.clock_widget, 'text')
            and status_bar.clock
        ):
            self.app.clock_widget.text = status_bar.clock

        if hasattr(self.app, 'temperature'):
            if status_bar.temperature is None:
                self.app.temperature.text = ''
            else:
                self.app.temperature.text = f'{status_bar.temperature:0.1f}󰔄'

        if hasattr(self.app, 'light'):
            if status_bar.light_level is None:
                self.app.light.color = (1, 1, 1, 1)
            else:
                v = min(status_bar.light_level, 140) / 140
                self.app.light.color = (1, 1, 1, v)

        if not hasattr(self.app, 'icons_layout'):
            return
        self.app.icons_layout.clear_widgets()
        icon_items = getattr(status_bar.icons, 'items', []) or []
        for icon_data in list(reversed(icon_items))[:4]:
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

        if hasattr(self.app, 'recording_sign'):
            self._update_sign_widget(
                sign=self.app.recording_sign,
                should_show=status_bar.is_recording or status_bar.is_recording_audio,
                color=(0, 0, 1, 1) if status_bar.is_recording else (0, 1, 0, 1),
            )

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

        pn_items = (
            getattr(status_bar.progress_notifications, 'items', []) or []
        )
        for pn in pn_items:
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
        pn: object,
        dp_func: Callable[[float], float],
    ) -> Widget:
        """Get existing or create new progress widget for a notification."""
        from ubo_gui.progress_ring import ProgressRingWidget
        from ubo_gui.spinner import SpinnerWidget

        pn_id = getattr(pn, 'id', '')
        pn_progress = getattr(pn, 'progress', None)

        if pn_progress is None:
            if pn_id not in self.app.notification_widgets or not isinstance(
                self.app.notification_widgets[pn_id][1],
                SpinnerWidget,
            ):
                widget: Widget = SpinnerWidget(
                    font_size=dp_func(16),
                    size_hint=(None, None),
                    pos_hint={'center_y': 0.5},
                    height=dp_func(16),
                    width=dp_func(16),
                )
                self.app.notification_widgets[pn_id] = (None, widget)
            return self.app.notification_widgets[pn_id][1]

        if pn_id not in self.app.notification_widgets or not isinstance(
            self.app.notification_widgets[pn_id][1],
            ProgressRingWidget,
        ):
            widget = ProgressRingWidget(
                background_color=(0.3, 0.3, 0.3, 1),
                height=dp_func(16),
                band_width=dp_func(7),
                size_hint=(None, None),
                pos_hint={'center_y': 0.5},
            )
            self.app.notification_widgets[pn_id] = (None, widget)
        return self.app.notification_widgets[pn_id][1]
