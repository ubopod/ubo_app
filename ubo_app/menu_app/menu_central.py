# ruff: noqa: D100, D101, D102, D107
from __future__ import annotations

import weakref
from functools import cached_property
from typing import TYPE_CHECKING

from debouncer import DebounceOptions, debounce
from ubo_gui.app import UboApp
from ubo_gui.menu.menu_widget import MenuPageWidget, MenuWidget
from ubo_gui.menu.stack_item import StackApplicationItem, StackItem, StackMenuItem
from ubo_gui.page import PageWidget
from ubo_gui.utils import mainthread_if_needed

from ubo_app.constants import DEBUG_MENU, USE_DUMB_UI
from ubo_app.logger import logger
from ubo_app.menu_app.home_page import HomePage
from ubo_app.menu_app.menu_notification_handler import MenuNotificationHandler
from ubo_app.store.core.types import (
    CloseApplicationEvent,
    MenuChooseByIconEvent,
    MenuChooseByIndexEvent,
    MenuChooseByLabelEvent,
    MenuGoBackEvent,
    MenuGoHomeEvent,
    MenuScrollDirection,
    MenuScrollEvent,
    OpenApplicationEvent,
    SetAreEnclosuresVisibleAction,
    SetMenuPathAction,
    StackPopAction,
    StackPopToRootAction,
    StackPushApplicationAction,
    StackPushMenuAction,
    StackPushNotificationAction,
    StackSetPageIndexAction,
)
from ubo_app.store.core.types import (
    MenuStackItem as ReduxMenuStackItem,
)
from ubo_app.store.main import store
from ubo_app.store.services.notifications import NotificationsDisplayEvent
from ubo_app.store.ubo_actions import get_registered_application
from ubo_app.utils.gui import UboPageWidget

if TYPE_CHECKING:
    from collections.abc import Sequence

    from kivy.uix.widget import Widget
    from ubo_gui.menu.types import Item, Menu


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

        self.menu_widget.bind(page_index=self.handle_page_index_change)
        self.menu_widget.bind(current_menu=self.handle_page_index_change)
        self.menu_widget.bind(title=self.handle_title_change)
        self.menu_widget.bind(stack=self.handle_stack_change)

        # Initialize ViewRenderer for dumb UI mode
        if USE_DUMB_UI:
            from ubo_app.menu_app.view_renderer import ViewRenderer

            self.view_renderer = ViewRenderer(self.menu_widget)

        if DEBUG_MENU:
            menu_representation = 'Menu:\n' + repr(self.menu_widget)
            self.menu_widget.bind(stack=lambda *_: logger.info(menu_representation))

        _self = weakref.ref(self)

        @store.autorun(lambda state: state.main.menu)
        @debounce(0.1, DebounceOptions(leading=True, trailing=True, time_window=0.1))
        def _(menu: Menu | None) -> None:
            self = _self()
            if not self or not menu:
                return
            self.menu_widget.set_root_menu(menu)

        # Phase 2.5: Validation autorun to verify Redux stack stays in sync
        if DEBUG_MENU:

            @store.autorun(lambda state: state.main.stack)
            def _validate_stack_sync(redux_stack: object) -> None:
                if not isinstance(redux_stack, tuple):
                    return
                self = _self()
                if not self:
                    return
                gui_stack = self.menu_widget.stack
                gui_len = len(gui_stack)
                redux_len = len(redux_stack)

                # Compare lengths
                if gui_len != redux_len:
                    logger.warning(
                        f'[STACK SYNC] Length mismatch! '
                        f'GUI: {gui_len}, Redux: {redux_len}',
                    )
                    return

                # Compare stack items
                for i, (gui_item, redux_item) in enumerate(
                    zip(gui_stack, redux_stack, strict=True),
                ):
                    gui_type = type(gui_item).__name__
                    redux_type = type(redux_item).__name__
                    if isinstance(gui_item, StackMenuItem):
                        if not isinstance(redux_item, ReduxMenuStackItem):
                            logger.warning(
                                f'[STACK SYNC] Type mismatch at [{i}]: '
                                f'GUI={gui_type}, Redux={redux_type}',
                            )
                        elif gui_item.page_index != redux_item.page_index:
                            logger.warning(
                                f'[STACK SYNC] Page index mismatch at [{i}]: '
                                f'GUI={gui_item.page_index}, '
                                f'Redux={redux_item.page_index}',
                            )
                    elif isinstance(gui_item, StackApplicationItem):
                        from ubo_app.store.core.types import (
                            ApplicationStackItem as ReduxAppItem,
                        )

                        if not isinstance(redux_item, ReduxAppItem):
                            logger.warning(
                                f'[STACK SYNC] Type mismatch at [{i}]: '
                                f'GUI={gui_type}, Redux={redux_type}',
                            )

                logger.debug(
                    f'[STACK SYNC] ✓ Stacks in sync: {redux_len} items',
                )

    def build(self) -> Widget | None:
        root = super().build()
        if root:
            self.menu_widget.padding_top = root.ids.header_layout.height
            self.menu_widget.padding_bottom = root.ids.footer_layout.height

        return root

    def handle_page_index_change(
        self: MenuAppCentral,
        *_: object,
    ) -> None:
        page_index = self.menu_widget.page_index

        # Dispatch enclosure visibility based on page index
        store.dispatch(
            SetAreEnclosuresVisibleAction(
                is_header_visible=page_index == 0,
                is_footer_visible=page_index >= self.menu_widget.pages - 1,
            ),
        )

        # Sync page index to Redux state (triggers ViewChangedEvent)
        store.dispatch(StackSetPageIndexAction(page_index=page_index))

    def handle_title_change(self: MenuAppCentral, _: MenuWidget, title: str) -> None:
        self.root.title = title

    def handle_stack_change(
        self: MenuAppCentral,
        _: MenuWidget,
        gui_stack: list[StackItem],
    ) -> None:
        # Legacy: Dispatch path for backward compatibility
        store.dispatch(
            SetMenuPathAction(
                path=[
                    stack_item.selection.key
                    for stack_item in gui_stack
                    if isinstance(stack_item, StackMenuItem) and stack_item.selection
                ],
                depth=len(gui_stack),
            ),
        )

        # Phase 2.5: Sync Redux stack with GUI stack
        # This validates our Redux stack actions produce correct state
        self._sync_redux_stack_with_gui(gui_stack)

    def _sync_redux_stack_with_gui(
        self: MenuAppCentral,
        gui_stack: list[StackItem],
    ) -> None:
        """Sync the Redux stack state with the GUI stack.

        This is an intermediate validation step (Phase 2.5) that ensures
        the Redux stack matches the GUI stack. After full migration,
        this will be inverted (GUI will follow Redux state).
        """
        state = store._state  # noqa: SLF001
        if state is None:
            return

        redux_stack = state.main.stack
        gui_len = len(gui_stack)
        redux_len = len(redux_stack)

        if gui_len > redux_len:
            self._handle_stack_push(gui_stack, redux_len)
        elif gui_len < redux_len:
            self._handle_stack_pop(gui_len, redux_len)
        elif gui_len > 0:
            self._handle_page_index_sync(gui_stack[-1], redux_stack[-1])

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
                # Try to get a meaningful application ID
                app = gui_item.application
                # Check if it's a notification widget first
                if hasattr(app, 'notification_id') and app.notification_id:
                    # This is a notification - push as notification
                    store.dispatch(
                        StackPushNotificationAction(
                            notification_id=app.notification_id,
                        ),
                    )
                else:
                    # Regular application - use class name as identifier
                    app_id = app.__class__.__name__
                    # Capture any useful properties for logging
                    init_kwargs: dict[str, str] = {}
                    # For NotificationInfo, capture the text content
                    if hasattr(app, 'text'):
                        text_val = getattr(app, 'text', None)
                        if DEBUG_MENU:
                            logger.debug(
                                '[STACK SYNC] App %s has text attr: %r',
                                app_id,
                                text_val[:100] if text_val else None,
                            )
                        if text_val:
                            init_kwargs['text'] = str(text_val)
                    store.dispatch(
                        StackPushApplicationAction(
                            application_id=app_id,
                            initialization_kwargs=init_kwargs,  # type: ignore[arg-type]
                        ),
                    )

    def _get_menu_key_for_item(
        self: MenuAppCentral,
        gui_stack: list[StackItem],
        index: int,
        gui_item: StackMenuItem,
    ) -> str:
        """Get the menu key for a stack item from parent's selection."""
        if index > 0:
            parent = gui_stack[index - 1]
            if (
                isinstance(parent, StackMenuItem)
                and parent.selection
                and parent.selection.item is gui_item
            ):
                return parent.selection.key
            menu_title = gui_item.menu.title
            return menu_title() if callable(menu_title) else (menu_title or '')
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
        redux_top: ReduxMenuStackItem | object,  # Could be any StackItemType
    ) -> None:
        """Sync page index if top items are menus with different indices."""
        if (
            isinstance(gui_top, StackMenuItem)
            and isinstance(redux_top, ReduxMenuStackItem)
            and gui_top.page_index != redux_top.page_index
        ):
            store.dispatch(StackSetPageIndexAction(page_index=gui_top.page_index))

    @cached_property
    def central(self: MenuAppCentral) -> Widget | None:
        """Build the main menu and initiate it."""
        self.root.title = self.menu_widget.title

        store.subscribe_event(
            NotificationsDisplayEvent,
            self.display_notification,
            keep_ref=False,
        )

        store.subscribe_event(
            OpenApplicationEvent,
            self.open_application,
            keep_ref=False,
        )
        store.subscribe_event(
            CloseApplicationEvent,
            self.close_application,
            keep_ref=False,
        )
        store.subscribe_event(
            MenuGoHomeEvent,
            self.go_home,
            keep_ref=False,
        )
        store.subscribe_event(
            MenuGoBackEvent,
            self.go_back,
            keep_ref=False,
        )
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
        store.subscribe_event(
            MenuScrollEvent,
            self.scroll,
            keep_ref=False,
        )

        return self.menu_widget

    @mainthread_if_needed
    def open_application(self: MenuAppCentral, event: OpenApplicationEvent) -> None:
        application = get_registered_application(event.application_id)
        self.menu_widget.open_application(
            application(*event.initialization_args, **event.initialization_kwargs),
        )

    def close_application(self: MenuAppCentral, event: CloseApplicationEvent) -> None:
        for item in self.menu_widget.stack:
            if (
                event.application_instance_id
                and isinstance(item, StackApplicationItem)
                and hasattr(item.application, 'id')
                and isinstance(item.application, UboPageWidget)
                and item.application.id == event.application_instance_id
            ):
                self.menu_widget.close_application(item.application)

    def go_home(self: MenuAppCentral, _: MenuGoHomeEvent) -> None:
        self.menu_widget.go_home()

    def go_back(self: MenuAppCentral, _: MenuGoBackEvent) -> None:
        self.menu_widget.go_back()

    def select_by_icon(self: MenuAppCentral, event: MenuChooseByIconEvent) -> None:
        current_page = self.menu_widget.current_screen
        if current_page is None:
            msg = 'No current page'
            raise ValueError(msg)
        if not isinstance(current_page, PageWidget):
            msg = 'Current page is not a StackMenuItem'
            raise TypeError(msg)
        if current_page.items is None:
            msg = 'No items in current page'
            raise TypeError(msg)
        items: Sequence[Item | None] = current_page.items
        filtered_items = [item for item in items if item and item.icon == event.icon]
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
        from ubo_gui.page import PageWidget

        current_page = self.menu_widget.current_screen
        if current_page is None:
            msg = 'No current page'
            raise ValueError(msg)
        if not isinstance(current_page, PageWidget):
            msg = 'Current page is not a StackMenuItem'
            raise TypeError(msg)
        if current_page.items is None:
            msg = 'No items in current page'
            raise TypeError(msg)
        items: Sequence[Item | None] = current_page.items
        filtered_items = [item for item in items if item and item.label == event.label]
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

    def scroll(self: MenuAppCentral, event: MenuScrollEvent) -> None:
        if event.direction == MenuScrollDirection.UP:
            self.menu_widget.go_up()
        elif event.direction == MenuScrollDirection.DOWN:
            self.menu_widget.go_down()
