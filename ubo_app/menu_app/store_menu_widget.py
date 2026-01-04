"""Store-driven menu widget that renders based on Redux store state."""

from __future__ import annotations

import weakref
from typing import TYPE_CHECKING

from kivy.properties import (
    BooleanProperty,
    ListProperty,
    NumericProperty,
    ObjectProperty,
    StringProperty,
)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import NoTransition, Screen, ScreenManager, SlideTransition
from ubo_gui.menu.constants import PAGE_SIZE
from ubo_gui.menu.widgets.menu_page_widget import MenuPageWidget
from ubo_gui.page import PageWidget

from ubo_app.logger import logger
from ubo_app.store.core.selectors import select_current_items
from ubo_app.store.core.types import (
    ApplicationStackItem,
    MenuChooseByIndexAction,
    MenuStackItem,
    NavigateClearAction,
    NavigatePopAction,
    SetPageIndexAction,
    StackItem,
)
from ubo_app.store.main import store
from ubo_app.store.ubo_actions import get_registered_application

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_gui.menu.types import Item, Menu


class StoreMenuWidget(BoxLayout):
    """Menu widget driven entirely by Redux store state.

    This widget subscribes to the store's navigation_stack and renders
    the appropriate view (menu page or application) based on state.
    It dispatches actions on user interaction rather than managing
    local state.
    """

    # Kivy properties for rendering
    padding_top: int = NumericProperty(0)
    padding_bottom: int = NumericProperty(0)
    render_surroundings: bool = BooleanProperty(defaultvalue=True)
    page_index: int = NumericProperty(0)
    pages: int = NumericProperty(1)
    title: str = StringProperty('')
    current_screen: Screen | None = ObjectProperty(None, allownone=True)
    depth: int = NumericProperty(0)

    # Stack property for backward compatibility with tests
    _stack: list[StackItem] = ListProperty([])
    _current_items: Sequence[Item | None] = ListProperty([])

    def __init__(self: StoreMenuWidget, **kwargs: object) -> None:
        """Initialize the store menu widget."""
        super().__init__(**kwargs)

        # Create screen manager for transitions
        self.screen_manager = ScreenManager(transition=NoTransition())
        self.add_widget(self.screen_manager)

        # Current menu page widget (cached for reuse)
        self._menu_page: MenuPageWidget | None = None
        self._menu_page_clone: MenuPageWidget | None = None

        # Subscribe to store for rendering updates
        _self = weakref.ref(self)

        @store.autorun(lambda state: state.main.navigation_stack)
        def on_stack_change(stack: tuple[StackItem, ...]) -> None:
            self_ = _self()
            if self_ is None:
                return
            self_.handle_stack_change(stack)

        @store.autorun(select_current_items)
        def on_items_change(items: Sequence[Item | None]) -> None:
            self_ = _self()
            if self_ is None:
                return
            self_.set_current_items(items)

        # Store the unsubscribe function for cleanup
        self._unsubscribe_stack = on_stack_change
        self._unsubscribe_items = on_items_change

    @property
    def stack(self: StoreMenuWidget) -> list[StackItem]:
        """Return navigation stack for backward compatibility."""
        return list(self._stack)

    @property
    def current_menu_items(self: StoreMenuWidget) -> Sequence[Item | None]:
        """Get current menu items (cached from store autorun)."""
        return self._current_items

    def set_current_items(self: StoreMenuWidget, items: Sequence[Item | None]) -> None:
        """Set current menu items (called by autorun)."""
        self._current_items = list(items)

    def handle_stack_change(
        self: StoreMenuWidget,
        stack: tuple[StackItem, ...],
    ) -> None:
        """Handle navigation stack changes from store."""
        logger.debug(
            'StoreMenuWidget: stack changed',
            extra={'stack_depth': len(stack)},
        )

        self.depth = len(stack)
        self._stack = list(stack)

        if not stack:
            # At home - render root menu
            self._render_home_menu()
        else:
            top = stack[-1]
            if isinstance(top, MenuStackItem):
                self._render_menu_page(top)
            elif isinstance(top, ApplicationStackItem):
                self._render_application(top)

    def _render_home_menu(self: StoreMenuWidget) -> None:
        """Render the root menu (home)."""
        from ubo_app.menu_app.home_page import HomePage

        self.page_index = 0
        self.pages = 1
        self.title = ''

        # Create or reuse home page
        home_page = HomePage(
            name='home',
            padding_bottom=self.padding_bottom,
            padding_top=self.padding_top,
        )
        home_page.items = self.current_menu_items

        self._switch_to_screen(home_page)

    def _render_menu_page(self: StoreMenuWidget, stack_item: MenuStackItem) -> None:
        """Render a menu page based on stack item."""
        items = self.current_menu_items
        self.page_index = stack_item.page_index
        self.pages = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
        self.title = stack_item.title or ''

        # Create menu page widget
        menu_page = MenuPageWidget(
            items,
            page_index=self.page_index,
            name=f'menu_{len(stack_item.menu_path)}_{self.page_index}',
            count=PAGE_SIZE,
            render_surroundings=self.render_surroundings,
            padding_bottom=self.padding_bottom,
            padding_top=self.padding_top,
        )

        self._switch_to_screen(menu_page)

    def _render_application(
        self: StoreMenuWidget,
        stack_item: ApplicationStackItem,
    ) -> None:
        """Render an application based on stack item."""
        self.title = stack_item.title or ''

        # Get the application class and instantiate it
        try:
            application_class = get_registered_application(stack_item.application_id)
            application = application_class(
                *stack_item.initialization_args,
                **stack_item.initialization_kwargs,
            )
            application.name = stack_item.instance_id
            application.padding_bottom = self.padding_bottom
            application.padding_top = self.padding_top

            self._switch_to_screen(application)
        except Exception:
            logger.exception(
                'Failed to create application',
                extra={'application_id': stack_item.application_id},
            )

    def _switch_to_screen(self: StoreMenuWidget, screen: Screen) -> None:
        """Switch to a new screen with transition."""
        # Add screen if not already present
        if screen.name not in [s.name for s in self.screen_manager.screens]:
            self.screen_manager.add_widget(screen)

        # Switch with appropriate transition
        if self.screen_manager.current != screen.name:
            self.screen_manager.transition = SlideTransition(direction='left')
            self.screen_manager.current = screen.name

        self.current_screen = screen

    # User interaction methods - dispatch actions to store

    def select(self: StoreMenuWidget, index: int) -> None:
        """Select a menu item by index."""
        store.dispatch(MenuChooseByIndexAction(index=index))

    def go_back(self: StoreMenuWidget) -> None:
        """Go back one level in navigation."""
        # Check if current screen handles go_back
        # Check if current screen handles go_back
        if (
            isinstance(self.current_screen, PageWidget)
            and self.current_screen.go_back()
        ):
            return
        store.dispatch(NavigatePopAction())

    def go_home(self: StoreMenuWidget) -> None:
        """Go to home (clear navigation stack)."""
        store.dispatch(NavigateClearAction())

    def go_up(self: StoreMenuWidget) -> None:
        """Scroll up (previous page)."""
        if isinstance(self.current_screen, PageWidget):
            self.current_screen.go_up()
            return

        if self.page_index > 0:
            store.dispatch(SetPageIndexAction(page_index=self.page_index - 1))
        elif self.pages > 1:
            # Wrap around to last page
            store.dispatch(SetPageIndexAction(page_index=self.pages - 1))

    def go_down(self: StoreMenuWidget) -> None:
        """Scroll down (next page)."""
        if isinstance(self.current_screen, PageWidget):
            self.current_screen.go_down()
            return

        if self.page_index < self.pages - 1:
            store.dispatch(SetPageIndexAction(page_index=self.page_index + 1))
        elif self.pages > 1:
            # Wrap around to first page
            store.dispatch(SetPageIndexAction(page_index=0))

    def open_application(
        self: StoreMenuWidget,
        application: PageWidget,
    ) -> None:
        """Open an application (for backward compatibility).

        Note: Prefer dispatching PushApplicationAction directly.
        """
        from ubo_app.store.core.types import PushApplicationAction

        # Get application ID if available
        app_id = getattr(application, 'application_id', type(application).__name__)
        title = getattr(application, 'title', '')

        store.dispatch(
            PushApplicationAction(
                application_id=app_id,
                title=title or '',
            ),
        )

    def close_application(self: StoreMenuWidget, application: PageWidget) -> None:
        """Close an application (for backward compatibility)."""
        from ubo_app.store.core.types import PopApplicationAction

        instance_id = getattr(application, 'id', application.name)
        store.dispatch(PopApplicationAction(instance_id=instance_id))

    def set_root_menu(self: StoreMenuWidget, _root_menu: Menu | None) -> None:
        """Set root menu (no-op, menu comes from store)."""
        # Menu is set in store.state.main.menu
        # This is here for API compatibility

