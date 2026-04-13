# ruff: noqa: D100, D101, D102, D107
from __future__ import annotations

import logging
from functools import cached_property
from typing import TYPE_CHECKING

from kivy.clock import mainthread
from ubo_gui.app import UboApp
from ubo_gui.menu.menu_widget import MenuWidget
from ubo_gui.menu.stack_item import StackMenuItem
from ubo_gui.menu.types import ActionItem, HeadlessMenu

from ubo_gui_client.constants import DEBUG_MENU
from ubo_gui_client.menu_notification_handler import MenuNotificationHandler
from ubo_gui_client.widgets.home_page import HomePage

if TYPE_CHECKING:
    from kivy.uix.screenmanager import Screen, TransitionBase
    from kivy.uix.widget import Widget
    from ubo_gui.menu.types import Menu

    from ubo_gui_client.app import UboGUIApp
    from ubo_gui_client.client import GUIClient

logger = logging.getLogger(__name__)

_SWAP_DURATION = 0.2


def _noop() -> None:
    """No-op action for menu items; real selection goes via gRPC."""


def _convert_proto_items_to_ubo(proto_items: list[object]) -> list[ActionItem]:
    """Convert proto Item objects to ubo_gui ActionItem objects."""
    result: list[ActionItem] = []
    for item in proto_items:
        label = getattr(item, 'label', None) or ''
        icon = getattr(item, 'icon', None)
        color = getattr(item, 'color', None) or (1, 1, 1, 1)
        background_color = getattr(item, 'background_color', None)
        is_short = getattr(item, 'is_short', None) or False

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


def _convert_proto_menu_to_ubo(proto_menu: object) -> Menu | None:
    """Convert a proto Menu to a ubo_gui Menu.

    The proto Menu is a oneof (headed_menu | headless_menu).
    We use betterproto.which_one_of to determine which field is set.
    """
    import betterproto

    if isinstance(proto_menu, betterproto.Message):
        _, source = betterproto.which_one_of(proto_menu, 'menu')
    else:
        source = None

    if source is None:
        return None

    title = getattr(source, 'title', '') or ''
    proto_items = getattr(source, 'items', []) or []
    items = _convert_proto_items_to_ubo(proto_items)

    return HeadlessMenu(title=title, items=items)


class MenuWidgetWithHomePage(MenuWidget):
    _next_transition_override: tuple[TransitionBase, str | None] | None = None

    @cached_property
    def home_page(self: MenuWidgetWithHomePage) -> HomePage:
        return HomePage(
            name='Page 1 0',
            padding_bottom=self.padding_bottom,
            padding_top=self.padding_top,
        )

    def _render_menu(  # type: ignore[override]
        self: MenuWidgetWithHomePage,
        menu: Menu,
    ) -> Widget:

        if self.depth <= 1:
            self.home_page.items = self.current_menu_items
            self.current_screen = self.home_page
            return self.home_page
        return super()._render_menu(menu)

    def _switch_to(
        self: MenuWidgetWithHomePage,
        screen: Screen | None,
        /,
        *,
        transition: TransitionBase,
        duration: float | None = None,
        direction: str | None = None,
    ) -> None:
        """Override to support transition overrides.

        When ``_next_transition_override`` is set, it replaces the transition
        and direction for one call.  This enables animated transitions from
        ``_replace_menu`` which normally hard-codes ``_no_transition``.
        """
        if self._next_transition_override is not None:
            override_transition, override_direction = self._next_transition_override
            self._next_transition_override = None
            super()._switch_to(
                screen,
                transition=override_transition,
                duration=duration,
                direction=override_direction,
            )
        else:
            super()._switch_to(
                screen,
                transition=transition,
                duration=duration,
                direction=direction,
            )

    def reset_to_root(self: MenuWidgetWithHomePage) -> bool:
        """Reset the navigation stack to root (depth 1) instantly.

        Unlike ``go_home()`` which uses an animated transition (0.3s),
        this performs an instant reset using ``_no_transition`` so that
        the caller can immediately push/open a new view without the home
        page flashing during the animation.

        Returns ``True`` if a reset was performed, ``False`` if already at root.
        """
        if self.depth <= 1 and self.current_application is None:
            logger.debug(
                '[MenuWidget] reset_to_root: already at root (depth=%d, app=None)',
                self.depth,
            )
            return False
        logger.info(
            '[MenuWidget] reset_to_root: instant reset (depth=%d, app=%s, stack=%d)',
            self.depth,
            type(self.current_application).__name__
            if self.current_application
            else 'None',
            len(self.stack),
        )
        from ubo_gui.menu.stack_item import StackApplicationItem

        with self.stack_lock:
            for item in self.stack[1:]:
                item.clear_subscriptions()
                if isinstance(item, StackApplicationItem):
                    item.application.dispatch('on_close')
            self.root.selection = None
            # Hide old screen immediately — _switch_to is deferred by
            # @mainthread so without this the old screen stays visible
            # for one frame while NoTransition completes.
            old = self.screen_manager.current_screen
            if old is not None:
                old.opacity = 0.0
            self.stack = self.stack[:1]
            self._switch_to(
                self.current_screen,
                transition=self._no_transition,
            )
        return True

    def _on_screen_changed(self: MenuWidgetWithHomePage, *_args: object) -> None:
        """Hide all ScreenManager children except the current screen.

        Bound to ``screen_manager.current`` changes. Ensures the home page
        (or any other old screen) doesn't bleed through transparent areas
        of the new screen.

        During animated transitions, the transition handlers manage opacity
        via ``_handle_transition_progress``; we skip here to avoid a
        one-frame flash where the old screen is hidden before the animation
        begins.
        """
        if self._running_transition_end_time is not None:
            return
        current = self.screen_manager.current_screen
        for child in self.screen_manager.children:
            child.opacity = 1.0 if child is current else 0.0

    def go_home_animated(self: MenuWidgetWithHomePage) -> bool:
        """Reset the navigation stack to root with a rise-in animation.

        Matches the original ``go_home()`` behaviour from the main branch.
        Unlike ``reset_to_root()`` which uses instant transition, this
        animates the return to home so the user sees visual feedback.

        Returns ``True`` if a reset was performed, ``False`` if already at root.
        """
        if self.depth <= 1 and self.current_application is None:
            return False
        logger.info(
            '[MenuWidget] go_home_animated: depth=%d, app=%s',
            self.depth,
            type(self.current_application).__name__
            if self.current_application
            else 'None',
        )
        from ubo_gui.menu.stack_item import StackApplicationItem

        with self.stack_lock:
            for item in self.stack[1:]:
                item.clear_subscriptions()
                if isinstance(item, StackApplicationItem):
                    item.application.dispatch('on_close')
            self.root.selection = None
            self.stack = self.stack[:1]
            self._switch_to(
                self.current_screen,
                transition=self._rise_in_transition,
            )
        return True

    def replace_top_with_application(
        self: MenuWidgetWithHomePage,
        application: object,
        *,
        animated: bool = False,
    ) -> None:
        """Replace whatever is at the current depth with an application.

        At any depth, this clears items above root and pushes the application.

        When ``animated`` is True, uses a swap transition for visual feedback.
        Otherwise uses instant (no) transition to prevent the home page from
        flashing.
        """
        import uuid

        from ubo_gui.menu.stack_item import StackApplicationItem
        from ubo_gui.page import PageWidget

        if not isinstance(application, PageWidget):
            msg = f'Expected PageWidget, got {type(application)}'
            raise TypeError(msg)

        logger.info(
            '[MenuWidget] replace_top_with_application: depth=%d, animated=%s',
            self.depth,
            animated,
        )
        with self.stack_lock:
            # Clean up items above root
            for item in self.stack[1:]:
                item.clear_subscriptions()
                if isinstance(item, StackApplicationItem):
                    item.application.dispatch('on_close')
            self.root.selection = None
            if not animated:
                # Hide old screen immediately — _switch_to is deferred by
                # @mainthread so without this the old screen stays visible
                # for one frame while NoTransition completes.
                old = self.screen_manager.current_screen
                if old is not None:
                    old.opacity = 0.0
            # Set stack to root only
            self.stack = self.stack[:1]
            application.name = uuid.uuid4().hex
            application.padding_bottom = self.padding_bottom
            application.padding_top = self.padding_top
            new_top = StackApplicationItem(application=application, parent=None)
            self.stack = [*self.stack, new_top]
            if animated:
                self._switch_to(
                    self.current_screen,
                    transition=self._swap_transition,
                    duration=_SWAP_DURATION,
                    direction='left',
                )
            else:
                self._switch_to(
                    self.current_screen,
                    transition=self._no_transition,
                )

    def replace_top_with_menu(
        self: MenuWidgetWithHomePage,
        menu: Menu,
    ) -> None:
        """Replace whatever is at the current depth with a menu — instantly.

        At any depth, this clears items above root and pushes the new menu
        using ``_no_transition``, so the home page never flashes.
        """
        from ubo_gui.menu.stack_item import StackApplicationItem, StackMenuItem

        logger.info(
            '[MenuWidget] replace_top_with_menu: depth=%d, title=%s',
            self.depth,
            menu.title,
        )
        with self.stack_lock:
            # Clean up items above root
            for item in self.stack[1:]:
                item.clear_subscriptions()
                if isinstance(item, StackApplicationItem):
                    item.application.dispatch('on_close')
            self.root.selection = None
            # Hide old screen immediately — _switch_to is deferred by
            # @mainthread so without this the old screen stays visible
            # for one frame while NoTransition completes.
            old = self.screen_manager.current_screen
            if old is not None:
                old.opacity = 0.0
            # Set stack to root + new menu
            new_top = StackMenuItem(menu=menu, page_index=0, parent=None)
            self.stack = [self.stack[0], new_top]
            # Instant transition — no home page flash
            self._switch_to(
                self.current_screen,
                transition=self._no_transition,
            )

    def push_menu(self: MenuWidgetWithHomePage, menu: Menu) -> None:
        """Push a menu onto the navigation stack (public wrapper)."""
        logger.info(
            '[MenuWidget] push_menu: title=%s (depth=%d)',
            menu.title,
            self.depth,
        )
        self._push(
            menu,
            transition=self._slide_transition,
            direction='left',
        )
        logger.debug(
            '[MenuWidget] push_menu: done (depth=%d)',
            self.depth,
        )

    def replace_top_menu(
        self: MenuWidgetWithHomePage,
        menu: Menu,
        *,
        page_index: int | None = None,
        scroll_direction: str | None = None,
    ) -> None:
        """Replace the top menu's content without changing the stack depth.

        If ``page_index`` is given, the page index of the current stack item is
        updated *before* the menu is replaced so that the rendered page matches
        the scroll-bar position from the first frame.

        If ``scroll_direction`` is provided (``'up'``/``'down'`` for page
        scroll, ``'left'``/``'right'`` for push/pop), a transition override is
        set so that ``_replace_menu``'s hardcoded ``_no_transition`` is
        replaced with a slide animation in the given direction.
        """
        if not self.stack:
            logger.warning('[MenuWidget] replace_top_menu: empty stack, skipping')
            return
        logger.debug(
            '[MenuWidget] replace_top_menu: title=%s, page=%s, scroll=%s (depth=%d)',
            menu.title,
            page_index,
            scroll_direction,
            self.depth,
        )
        top = self.top
        if not isinstance(top, StackMenuItem):
            return

        if page_index is not None:
            top.page_index = page_index
        if scroll_direction:
            self._next_transition_override = (
                self._slide_transition,
                scroll_direction,
            )
        try:
            self._replace_menu(top, menu)
        finally:
            # Clear override if _replace_menu didn't reach _switch_to
            # (e.g. new_item was not self.top in a recursive call).
            self._next_transition_override = None


def _patch_transition_handlers(widget: MenuWidgetWithHomePage) -> None:
    """Patch transition handlers to guard against race conditions.

    Patches two classes of bugs in ubo_gui's ``TransitionsMixin``:

    1. ``_handle_transition_progress`` and ``_handle_transition_complete``
       access ``transition.screen_out`` / ``screen_in`` without null checks.
       Rapid view switching can clear these references.

    2. ``_switch_to`` schedules a lambda that accesses ``transition_queue[0]``
       without checking if the queue is still non-empty.  Rapid scrolling can
       drain the queue before the scheduled lambda fires, causing IndexError.

    Note: accesses private TransitionsMixin internals (transition_queue,
    _transition_progress_lock, _running_transition_end_time, _perform_switch).
    Review after ubo_gui upgrades.

    This monkey-patches the handlers with null-safe wrappers.
    """
    original_progress = widget._handle_transition_progress  # noqa: SLF001
    original_complete = widget._handle_transition_complete  # noqa: SLF001

    def _safe_progress(
        transition: TransitionBase,
        progression: float,
    ) -> None:
        if getattr(transition, 'screen_out', None) is None or getattr(
            transition,
            'screen_in',
            None,
        ) is None:
            logger.warning(
                '[MenuWidget] Transition progress with None screen'
                ' (screen_out=%s, screen_in=%s)',
                getattr(transition, 'screen_out', 'N/A'),
                getattr(transition, 'screen_in', 'N/A'),
            )
            return
        original_progress(transition, progression)

    def _safe_complete(transition: TransitionBase) -> None:
        if getattr(transition, 'screen_out', None) is None or getattr(
            transition,
            'screen_in',
            None,
        ) is None:
            logger.warning(
                '[MenuWidget] Transition complete with None screen'
                ' (screen_out=%s, screen_in=%s)',
                getattr(transition, 'screen_out', 'N/A'),
                getattr(transition, 'screen_in', 'N/A'),
            )
            # Clear the running state and process queued transitions
            with widget._transition_progress_lock:  # noqa: SLF001
                if widget.transition_queue:
                    (
                        (screen, next_transition, direction, duration),
                        *widget.transition_queue,
                    ) = widget.transition_queue
                    widget._perform_switch(  # noqa: SLF001
                        screen,
                        transition=next_transition,
                        duration=duration,
                        direction=direction,
                    )
                else:
                    widget._running_transition_end_time = None  # noqa: SLF001
            return
        original_complete(transition)

    widget._handle_transition_progress = _safe_progress  # noqa: SLF001
    widget._handle_transition_complete = _safe_complete  # noqa: SLF001


def _patch_switch_to_on_class() -> None:
    """Patch ``TransitionsMixin._switch_to`` at class level.

    ``MenuWidgetWithHomePage._switch_to`` delegates to
    ``super()._switch_to()`` (i.e. ``TransitionsMixin._switch_to``),
    so instance-level patches are bypassed.  We patch the class method
    directly to guard the scheduled lambda against empty ``transition_queue``.
    """
    from ubo_gui.menu._transitions import TransitionsMixin

    def _safe_switch_to(
        self: TransitionsMixin,
        screen: Screen | None,
        /,
        *,
        transition: TransitionBase,
        duration: float | None = None,
        direction: str | None = None,
    ) -> None:
        import time

        from kivy.clock import Clock

        if screen is self.screen_manager.current_screen:
            return
        if duration is None:
            duration = (
                0 if transition is self._no_transition else 0.3
            )
        with self._transition_progress_lock:
            if self._running_transition_end_time is not None:
                self.transition_queue.append(
                    (screen, transition, direction, duration),
                )
                if self._running_transition_end_time < time.time():

                    def _guarded_complete(
                        _: object,
                        _self: TransitionsMixin = self,
                    ) -> None:
                        if _self.transition_queue:
                            _self._handle_transition_complete(  # noqa: SLF001
                                _self.transition_queue[0][1],
                            )

                    Clock.schedule_once(_guarded_complete)
            else:
                self._running_transition_end_time = (
                    time.time() + duration + 2
                    if transition is not self._no_transition
                    else None
                )
                self._is_preparation_in_progress = True
                self._perform_switch(
                    screen,
                    transition=transition,
                    duration=duration,
                    direction=direction,
                )

    TransitionsMixin._switch_to = _safe_switch_to  # type: ignore[assignment]  # noqa: SLF001


_patch_switch_to_on_class()


class MenuAppCentral(MenuNotificationHandler, UboApp):
    grpc_client: GUIClient
    menu_widget: MenuWidgetWithHomePage

    def __init__(self: MenuAppCentral, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.menu_widget = MenuWidgetWithHomePage(render_surroundings=True)  # pyright: ignore[reportIncompatibleVariableOverride]
        self._last_page_index: int | None = None
        self._last_header_visible: bool | None = None
        self._last_footer_visible: bool | None = None

        _patch_transition_handlers(self.menu_widget)

        # Ensure inactive screens are hidden whenever the current screen changes.
        # This prevents the home page (with gauges) from bleeding through
        # transparent areas of menu/notification screens.
        self.menu_widget.screen_manager.bind(
            current=self.menu_widget._on_screen_changed,  # noqa: SLF001
        )

        self._setup_bindings()

    def _setup_bindings(self) -> None:
        """Set up Kivy property bindings."""
        self.menu_widget.bind(page_index=self.handle_page_index_change)
        self.menu_widget.bind(pages=self.handle_pages_change)
        self.menu_widget.bind(title=self.handle_title_change)

        if DEBUG_MENU:
            menu_representation = 'Menu:\n' + repr(self.menu_widget)
            self.menu_widget.bind(
                stack=lambda *_: logger.info(menu_representation),
            )

    def setup_view_renderer(self: MenuAppCentral) -> None:
        """Initialize ViewRenderer after gRPC connection is established."""
        from typing import cast

        from ubo_gui_client.view_renderer import ViewRenderer

        app = cast('UboGUIApp', self)
        self.view_renderer = ViewRenderer(
            self.menu_widget,
            app,
            self.grpc_client,
        )

        # Now that we're connected, dispatch initial visibility
        self.handle_page_index_change()

    @mainthread
    def _on_root_menu_changed(self: MenuAppCentral, proto_menu: object) -> None:
        """Handle root menu updates from gRPC."""
        ubo_menu = _convert_proto_menu_to_ubo(proto_menu)
        if ubo_menu is None:
            return

        if DEBUG_MENU:
            logger.info(
                '[MenuAppCentral] Root menu updated: title=%s, items=%d',
                ubo_menu.title,
                len(ubo_menu.items) if not callable(ubo_menu.items) else -1,
            )

        self.menu_widget.set_root_menu(ubo_menu)

    def build(self) -> Widget | None:
        root = super().build()
        if root:
            self.menu_widget.padding_top = root.ids.header_layout.height
            self.menu_widget.padding_bottom = root.ids.footer_layout.height

        return root

    def _dispatch_enclosure_visibility(self: MenuAppCentral) -> None:
        """Update header/footer visibility based on current page index."""
        page_index = self.menu_widget.page_index
        is_header_visible = page_index == 0
        is_footer_visible = page_index >= self.menu_widget.pages - 1

        # Update the local GUI widgets directly
        self.handle_is_header_visible_change(is_header_visible)
        self.handle_is_footer_visible_change(is_footer_visible)

        # Skip gRPC dispatch if values haven't changed (avoids flood during
        # view transitions where page_index/pages properties fire rapidly)
        if (
            is_header_visible == self._last_header_visible
            and is_footer_visible == self._last_footer_visible
        ):
            return
        self._last_header_visible = is_header_visible
        self._last_footer_visible = is_footer_visible

        self.grpc_client.dispatch_set_enclosures_visible(
            header=is_header_visible,
            footer=is_footer_visible,
        )

    def handle_page_index_change(
        self: MenuAppCentral,
        *_: object,
    ) -> None:
        page_index = self.menu_widget.page_index

        if self._last_page_index == page_index:
            return
        self._last_page_index = page_index

        self._dispatch_enclosure_visibility()

    def handle_pages_change(
        self: MenuAppCentral,
        *_: object,
    ) -> None:
        """Handle pages count changes - update footer visibility."""
        self._dispatch_enclosure_visibility()

    def handle_title_change(
        self: MenuAppCentral,
        _: MenuWidget,
        title: str,
    ) -> None:
        self.root.title = title

    @cached_property
    def central(self: MenuAppCentral) -> Widget | None:
        """Build the main menu and return the widget."""
        self.root.title = self.menu_widget.title
        return self.menu_widget
