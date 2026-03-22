# ruff: noqa: D100, D101, D102, D107
from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING

from ubo_gui.app import UboApp
from ubo_gui.menu.menu_widget import MenuPageWidget, MenuWidget
from ubo_gui.menu.stack_item import StackApplicationItem, StackItem, StackMenuItem
from ubo_gui.utils import mainthread_if_needed

from ubo_app.constants import DEBUG_MENU
from ubo_app.logger import logger
from ubo_app.menu_app.home_page import HomePage
from ubo_app.menu_app.menu_notification_handler import MenuNotificationHandler
from ubo_app.store.core.types import (
    ApplicationStackItem,
    MenuChooseByIconEvent,
    MenuChooseByIndexEvent,
    MenuChooseByLabelEvent,
    MenuStackItem,
    SetAreEnclosuresVisibleAction,
    StackPopAction,
    StackPopToRootAction,
    StackPushApplicationAction,
    StackPushMenuAction,
    StackPushNotificationAction,
    StackSetPageIndexAction,
)
from ubo_app.store.main import store
from ubo_app.store.services.notifications import NotificationsDisplayEvent
from ubo_app.store.ubo_actions import get_registered_application

if TYPE_CHECKING:
    from kivy.uix.widget import Widget
    from ubo_gui.menu.types import Item, Menu

    from ubo_app.store.core.types import StackItemType


class MenuWidgetWithHomePage(MenuWidget):
    @cached_property
    def home_page(self: MenuWidgetWithHomePage) -> HomePage:
        return HomePage(
            name='Page 1 0',
            padding_bottom=self.padding_bottom,
            padding_top=self.padding_top,
        )

    def _render_menu(self: MenuWidgetWithHomePage, menu: Menu) -> MenuPageWidget:
        if self.depth <= 1:
            self.home_page.items = self.current_menu_items
            self.current_screen = self.home_page
            return self.home_page
        return super()._render_menu(menu)


class MenuAppCentral(MenuNotificationHandler, UboApp):
    def __init__(self: MenuAppCentral, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.menu_widget = MenuWidgetWithHomePage(render_surroundings=True)
        self._last_page_index: int | None = None  # Track to avoid redundant dispatches

        self._setup_bindings()

    def _setup_bindings(self) -> None:
        """Set up Kivy property bindings."""
        self.menu_widget.bind(page_index=self.handle_page_index_change)
        self.menu_widget.bind(pages=self.handle_pages_change)
        self.menu_widget.bind(title=self.handle_title_change)
        self.menu_widget.bind(stack=self.handle_stack_change)

        # Ensure initial visibility state is dispatched
        self.handle_page_index_change()

        # Initialize ViewRenderer for dumb UI architecture
        from ubo_app.menu_app.view_renderer import ViewRenderer

        self.view_renderer = ViewRenderer(self.menu_widget, self)

        if DEBUG_MENU:
            menu_representation = 'Menu:\n' + repr(self.menu_widget)
            self.menu_widget.bind(stack=lambda *_: logger.info(menu_representation))

    def _get_home_menu_items(self) -> list:
        """Read home menu items from the HOME_MENU_ID dynamic menu.

        The dynamic menu is populated by setup_core_dynamic_menus() during
        store initialization, so it is guaranteed to be available here.
        """
        from ubo_gui.menu.types import ActionItem

        from ubo_app.store.core.menus import HOME_MENU_ID

        items: list[ActionItem] = []

        @store.with_state(lambda state: state.dynamic_menus)
        def _get_home_items(dynamic_menus_state: object) -> None:
            home_menu = dynamic_menus_state.menus.get(HOME_MENU_ID)  # type: ignore[union-attr]
            if home_menu:
                for item_data in home_menu.items:
                    if item_data:
                        kwargs: dict = {
                            'label': item_data.label,
                            'icon': item_data.icon,
                            'is_short': item_data.is_short,
                            'action': lambda: None,
                        }
                        if item_data.color:
                            kwargs['color'] = item_data.color
                        if item_data.background_color:
                            kwargs['background_color'] = item_data.background_color
                        items.append(ActionItem(**kwargs))

        _get_home_items()
        return items

    def build(self) -> Widget | None:
        root = super().build()
        if root:
            self.menu_widget.padding_top = root.ids.header_layout.height
            self.menu_widget.padding_bottom = root.ids.footer_layout.height

        # Set root menu AFTER padding is set so the HomePage cached property
        # is created with the correct padding_top/padding_bottom values.
        from ubo_gui.menu.types import HeadlessMenu

        items = self._get_home_menu_items()
        self.menu_widget.set_root_menu(
            HeadlessMenu(title='', items=items),
        )

        return root

    def _dispatch_enclosure_visibility(self: MenuAppCentral) -> None:
        """Dispatch enclosure visibility based on current page index and pages."""
        page_index = self.menu_widget.page_index
        store.dispatch(
            SetAreEnclosuresVisibleAction(
                is_header_visible=page_index == 0,
                is_footer_visible=page_index >= self.menu_widget.pages - 1,
            ),
        )

    def handle_page_index_change(
        self: MenuAppCentral,
        *_: object,
    ) -> None:
        page_index = self.menu_widget.page_index

        # Skip if page index hasn't actually changed (avoid redundant dispatches)
        if self._last_page_index == page_index:
            return
        self._last_page_index = page_index

        # Dispatch enclosure visibility based on page index
        self._dispatch_enclosure_visibility()

        # Sync page index to Redux state (triggers ViewChangedEvent)
        store.dispatch(StackSetPageIndexAction(page_index=page_index))

    def handle_pages_change(
        self: MenuAppCentral,
        *_: object,
    ) -> None:
        """Handle pages count changes - update footer visibility.

        When the total pages count changes, footer visibility may need to update.
        The footer should only show on the last page.
        """
        self._dispatch_enclosure_visibility()

    def handle_title_change(self: MenuAppCentral, _: MenuWidget, title: str) -> None:
        if self.root and title:
            self.root.title = title

    def handle_stack_change(
        self: MenuAppCentral,
        _: MenuWidget,
        gui_stack: list[StackItem],
    ) -> None:
        """Sync Redux stack state with GUI stack changes.

        This ensures Redux state tracks the GUI navigation state.
        When GUI navigates (push/pop), we dispatch corresponding Redux actions.
        """
        self._sync_stack_state_with_gui(gui_stack)

    @store.with_state(lambda state: state.main.stack)
    def _sync_stack_state_with_gui(
        self: MenuAppCentral,
        stack_state: tuple[StackItemType, ...],
        gui_stack: list[StackItem],
    ) -> None:
        """Sync the Redux stack state with the GUI stack.

        Dispatches Redux actions to keep the stack in sync with GUI navigation.
        """
        gui_len = len(gui_stack)
        redux_len = len(stack_state)

        if gui_len > redux_len:
            self._handle_stack_push(gui_stack, redux_len)
        elif gui_len < redux_len:
            self._handle_stack_pop(gui_len, redux_len)
        elif gui_len > 0:
            self._handle_page_index_sync(gui_stack[-1], stack_state[-1])

    def _handle_stack_push(
        self: MenuAppCentral,
        gui_stack: list[StackItem],
        start_index: int,
    ) -> None:
        """Push new items from GUI stack to Redux stack."""
        for i in range(start_index, len(gui_stack)):
            gui_item = gui_stack[i]
            if isinstance(gui_item, StackMenuItem):
                menu_key = self._get_menu_key_for_item(gui_stack, i, gui_item)
                store.dispatch(StackPushMenuAction(menu_key=menu_key))
            elif isinstance(gui_item, StackApplicationItem):
                app = gui_item.application
                # Check if it's a notification widget
                if hasattr(app, 'notification_id') and app.notification_id:
                    store.dispatch(
                        StackPushNotificationAction(notification_id=app.notification_id),
                    )
                else:
                    app_id = app.__class__.__name__
                    store.dispatch(StackPushApplicationAction(application_id=app_id))

    def _get_menu_key_for_item(
        self: MenuAppCentral,
        gui_stack: list[StackItem],
        index: int,
        gui_item: StackMenuItem,
    ) -> str:
        """Get the menu key for a stack item from parent's selection."""
        if index > 0:
            parent = gui_stack[index - 1]
            if isinstance(parent, StackMenuItem) and parent.selection:
                return parent.selection.key
            menu_title = gui_item.menu.title
            if callable(menu_title):
                return str(menu_title())
            return str(menu_title) if menu_title else ''
        return ''

    def _handle_stack_pop(
        self: MenuAppCentral,
        gui_len: int,
        redux_len: int,
    ) -> None:
        """Pop items from Redux stack to match GUI stack."""
        if gui_len == 1:
            store.dispatch(StackPopToRootAction())
        else:
            store.dispatch(StackPopAction(count=redux_len - gui_len))

    def _handle_page_index_sync(
        self: MenuAppCentral,
        gui_top: StackItem,
        redux_top: MenuStackItem | object,
    ) -> None:
        """Sync page index if top items are menus with different indices."""
        if (
            isinstance(gui_top, StackMenuItem)
            and isinstance(redux_top, MenuStackItem)
            and gui_top.page_index != redux_top.page_index
        ):
            store.dispatch(StackSetPageIndexAction(page_index=gui_top.page_index))

    @cached_property
    def central(self: MenuAppCentral) -> Widget | None:
        """Build the main menu and initiate it."""
        from redux import AutorunOptions

        self.root.title = self.menu_widget.title

        store.subscribe_event(
            NotificationsDisplayEvent,
            self.display_notification,
            keep_ref=False,
        )

        # Autorun on stack changes (replaces StackChangedEvent subscription)
        store.autorun(
            lambda state: state.main.stack,
            options=AutorunOptions(keep_ref=False),
        )(self._on_stack_changed)

        # Autorun on page index of top stack item
        store.autorun(
            lambda state: (
                state.main.stack[-1].page_index
                if state.main.stack
                and isinstance(state.main.stack[-1], MenuStackItem)
                else 0
            ),
            options=AutorunOptions(keep_ref=False),
        )(self._on_page_index_changed)

        store.subscribe_event(
            MenuChooseByIconEvent,
            self.select_by_icon,
            keep_ref=False,
        )
        store.subscribe_event(
            MenuChooseByLabelEvent,
            self.select_by_label,
            keep_ref=False,
        )
        store.subscribe_event(
            MenuChooseByIndexEvent,
            self.select_by_index,
            keep_ref=False,
        )

        return self.menu_widget

    @mainthread_if_needed
    def _on_stack_changed(
        self: MenuAppCentral,
        new_stack: tuple[StackItemType, ...],
    ) -> None:
        """Sync the Kivy widget with Redux stack changes."""
        gui_depth = self.menu_widget.depth
        new_depth = len(new_stack)

        if new_depth < gui_depth:
            # Pop: navigate back or home
            if new_depth <= 1:
                self.menu_widget.go_home()
            else:
                for _ in range(gui_depth - new_depth):
                    self.menu_widget.go_back()
        elif new_depth > gui_depth:
            # Push each new item in order (handles multi-step pushes).
            # Note: NotificationStackItem is handled via
            # NotificationsDisplayEvent, not here.
            for i in range(gui_depth, new_depth):
                new_item = new_stack[i]
                if isinstance(new_item, ApplicationStackItem):
                    application = get_registered_application(
                        new_item.application_id,
                    )
                    self.menu_widget.open_application(
                        application(
                            *new_item.initialization_args,
                            **new_item.initialization_kwargs,
                        ),
                    )
                elif isinstance(new_item, MenuStackItem):
                    menu = self._build_menu_for_stack(
                        new_stack[: i + 1],
                    )
                    if menu:
                        self.menu_widget._push(  # noqa: SLF001
                            menu,
                            transition=self.menu_widget._slide_transition,  # noqa: SLF001
                            direction='left',
                        )

    @mainthread_if_needed
    def _on_page_index_changed(
        self: MenuAppCentral,
        page_index: int,
    ) -> None:
        """Sync the Kivy widget with Redux page index changes."""
        current_page = self.menu_widget.page_index
        if current_page < page_index:
            for _ in range(page_index - current_page):
                self.menu_widget.go_down()
        elif current_page > page_index:
            for _ in range(current_page - page_index):
                self.menu_widget.go_up()

    @store.with_state(lambda state: state.dynamic_menus)
    def _build_menu_for_stack(
        self: MenuAppCentral,
        dynamic_menus_state: object,
        new_stack: tuple[StackItemType, ...],
    ) -> Menu | None:
        """Build a HeadlessMenu for a MenuStackItem push.

        Resolves the stack's path to a dynamic menu ID via path matchers,
        then converts the dynamic menu items to ActionItems.
        """
        from ubo_gui.menu.types import ActionItem, HeadlessMenu

        from ubo_app.store.core.stack_ops import derive_path_from_stack
        from ubo_app.store.core.view_registry import get_menu_id_for_path

        path = derive_path_from_stack(new_stack)
        menu_id = get_menu_id_for_path(path)
        if not menu_id:
            return None

        dynamic_menu = dynamic_menus_state.menus.get(menu_id)  # type: ignore[union-attr]
        if not dynamic_menu:
            return None

        items: list[ActionItem] = []
        for item_data in dynamic_menu.items:
            if item_data:
                kwargs: dict = {
                    'label': item_data.label,
                    'icon': item_data.icon,
                    'is_short': item_data.is_short,
                    'action': lambda: None,
                }
                if item_data.color:
                    kwargs['color'] = item_data.color
                if item_data.background_color:
                    kwargs['background_color'] = item_data.background_color
                items.append(ActionItem(**kwargs))

        return HeadlessMenu(title=dynamic_menu.title, items=items)

    def _get_selectable_items(self: MenuAppCentral) -> list[Item]:
        """Get items available for selection.

        When an application (e.g. notification) is on top, use its items.
        Otherwise use current_menu_items for full pagination support.
        """
        current_app = self.menu_widget.current_application
        if current_app is not None:
            return [item for item in current_app.items if item is not None]
        items = self.menu_widget.current_menu_items
        if items is None:
            return []
        return [item for item in items if item is not None]

    def select_by_icon(self: MenuAppCentral, event: MenuChooseByIconEvent) -> None:
        items = self._get_selectable_items()
        filtered_items = [item for item in items if item.icon == event.icon]
        if not filtered_items:
            msg = f'No item with icon "{event.icon}"'
            raise ValueError(msg)
        if len(filtered_items) > 1:
            msg = (
                f'Expected 1 item with icon "{event.icon}", found '
                f'"{len(filtered_items)}"'
            )
            raise ValueError(msg)
        self.menu_widget.select_item(filtered_items[0], parent=self.menu_widget.top)

    def select_by_label(
        self: MenuAppCentral,
        event: MenuChooseByLabelEvent,
    ) -> None:
        items = self._get_selectable_items()
        filtered_items = [item for item in items if item.label == event.label]
        if not filtered_items:
            msg = f'No item with label "{event.label}"'
            raise ValueError(msg)
        if len(filtered_items) > 1:
            msg = (
                f'Expected 1 item with label "{event.label}", found '
                f'"{len(filtered_items)}"'
            )
            raise ValueError(msg)
        self.menu_widget.select_item(filtered_items[0], parent=self.menu_widget.top)

    def select_by_index(
        self: MenuAppCentral,
        event: MenuChooseByIndexEvent,
    ) -> None:
        self.menu_widget.select(event.index)
