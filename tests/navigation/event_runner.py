"""Synchronous production-event runner for fast navigation tests."""

from __future__ import annotations

import importlib
import sys
from dataclasses import replace
from functools import wraps
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, cast

from redux import CompleteReducerResult

import ubo_app.store.core.view_computation as _view_computation
import ubo_app.store.services.notifications as _notifications_module

# Not used directly — imported so it lands in the collection-time module
# snapshot below. The notification-display handler lazily imports it by its
# dotted name at call time, while tests monkeypatch it through the
# `ubo_app.utils` package attribute; unless the sys.modules entry survives,
# those two paths resolve to different module objects after an `app_context`
# cleanup and the monkeypatch silently misses.
import ubo_app.utils.async_  # noqa: F401
from tests.navigation.conftest import (
    ReducerRunner,
    compute_view_from_dynamic_menus,
    reducer,
)
from ubo_app.store.core.types import (
    ExecuteMenuActionEvent,
    MainAction,
    MainState,
    MenuChooseByIconEvent,
    MenuChooseByIndexEvent,
    MenuChooseByLabelEvent,
    NotificationStackItem,
    ViewData,
)
from ubo_app.store.services.notifications import (
    Notification,
    NotificationsClearEvent,
    NotificationsDisplayEvent,
    NotificationsState,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from redux import BaseAction, BaseEvent

    from ubo_app.store.core.types import DynamicMenuData, MainEvent
    from ubo_app.store.main import RootState


class _RunnerStore:
    """Minimal store API used by production menu event handlers."""

    def __init__(self, runner: NavigationEventRunner) -> None:
        self.runner = runner

    def dispatch(self, *actions: BaseAction) -> None:
        """Feed production-handler dispatches back into the runner."""
        for action in actions:
            self.runner.dispatch(action)

    def with_state(self, selector: Callable) -> Callable:
        """Provide the decorator form of ``Store.with_state``."""
        def decorator(function: Callable) -> Callable:
            @wraps(function)
            def wrapped(*args: object, **kwargs: object) -> object:
                return function(
                    selector(self.runner.root_state),
                    *args,
                    **kwargs,
                )

            return wrapped

        return decorator


# The `ubo_app` module graph as it stands at collection time, when this module
# is imported. `_load_menu_event_handlers` re-imports the production handlers,
# and the handlers lazily import further `ubo_app` modules at call time; after
# an `app_context` test's sys.modules cleanup (tests/fixtures/app.py) those
# imports would resolve to freshly re-imported modules whose classes fail
# `isinstance` against the collection-generation ones these tests construct —
# every dispatch then becomes a silent no-op. Re-seeding sys.modules keeps the
# whole graph in one generation. `setdefault` so a module that legitimately
# re-imported meanwhile is left alone.
_UBO_MODULES_SNAPSHOT = {
    name: module
    for name, module in sys.modules.items()
    if name.startswith('ubo_app')
}


def _restore_collection_generation_modules() -> None:
    for name, module in _UBO_MODULES_SNAPSHOT.items():
        sys.modules.setdefault(name, module)


def _load_menu_event_handlers(fake_store: _RunnerStore) -> ModuleType:
    """Load production handlers against a detached, synchronous test store."""
    _restore_collection_generation_modules()
    handler_key = 'ubo_app.store.core.menu_event_handlers'
    notifications_key = 'ubo_app.store.services.notifications'
    store_key = 'ubo_app.store.main'
    previous_handler = sys.modules.pop(handler_key, None)
    previous_notifications = sys.modules.get(notifications_key)
    previous_store = sys.modules.get(store_key)
    fake_store_module = ModuleType(store_key)
    fake_store_module.__dict__['store'] = fake_store
    sys.modules[notifications_key] = _notifications_module
    sys.modules[store_key] = fake_store_module

    try:
        handlers = importlib.import_module(handler_key)
    finally:
        sys.modules.pop(handler_key, None)
        if previous_handler is not None:
            sys.modules[handler_key] = previous_handler
        if previous_notifications is None:
            sys.modules.pop(notifications_key, None)
        else:
            sys.modules[notifications_key] = previous_notifications
        if previous_store is None:
            sys.modules.pop(store_key, None)
        else:
            sys.modules[store_key] = previous_store

    return handlers


class NavigationEventRunner(ReducerRunner):
    """Run reducer actions and synchronously pump their production UI events."""

    def __init__(
        self,
        state: MainState,
        dynamic_menus: dict[str, DynamicMenuData] | None = None,
        path_mappings: dict[tuple[str, ...], str] | None = None,
    ) -> None:
        """Initialize state, fake store, and production event routes."""
        super().__init__(state, dynamic_menus, path_mappings)
        self.notifications = NotificationsState(notifications=(), unread_count=0)
        self.dispatched_actions: list[BaseAction] = []
        self._store = _RunnerStore(self)
        self.handlers = _load_menu_event_handlers(self._store)
        self._event_handlers: tuple[tuple[type[BaseEvent], Callable], ...] = (
            (
                MenuChooseByIndexEvent,
                self.handlers._handle_choose_by_index,  # noqa: SLF001
            ),
            (
                MenuChooseByIconEvent,
                self.handlers._handle_choose_by_icon,  # noqa: SLF001
            ),
            (
                MenuChooseByLabelEvent,
                self.handlers._handle_choose_by_label,  # noqa: SLF001
            ),
            (
                ExecuteMenuActionEvent,
                self.handlers._handle_execute_menu_action,  # noqa: SLF001
            ),
            (
                NotificationsDisplayEvent,
                self.handlers._handle_notification_display,  # noqa: SLF001
            ),
            (
                NotificationsClearEvent,
                self.handlers._handle_notification_clear_callback,  # noqa: SLF001
            ),
        )
        self._sync_current_view()

    @property
    def root_state(self) -> RootState:
        """Return the minimal RootState shape consumed by UI logic."""
        return cast(
            'RootState',
            SimpleNamespace(main=self.state, notifications=self.notifications),
        )

    @property
    def view(self) -> ViewData:
        """Return the same current view that production handlers inspect."""
        assert self.state.current_view is not None
        return self.state.current_view

    def set_notifications(self, *notifications: Notification) -> None:
        """Replace backing notifications and recompute the visible view."""
        normalized = tuple(
            self._normalize_notification(notification)
            for notification in notifications
        )
        self.notifications = replace(
            self.notifications,
            notifications=normalized,
            unread_count=sum(not item.is_read for item in normalized),
        )
        self._sync_current_view()

    @staticmethod
    def _normalize_notification(notification: Notification) -> Notification:
        """Normalize reloaded notification enums to the runner's module."""
        display_type = _notifications_module.NotificationDisplayType(
            notification.display_type.value,
        )
        if notification.display_type is display_type:
            return notification
        return replace(notification, display_type=display_type)

    def handle_event(self, event: BaseEvent) -> None:
        """Route an event through the matching production handler."""
        for event_type, handler in self._event_handlers:
            if (
                isinstance(event, event_type)
                or type(event).__name__ == event_type.__name__
            ):
                if event_type is NotificationsDisplayEvent:
                    notification_event = cast(
                        'NotificationsDisplayEvent',
                        event,
                    )
                    event = NotificationsDisplayEvent(
                        notification=self._normalize_notification(
                            notification_event.notification,
                        ),
                        index=notification_event.index,
                        count=notification_event.count,
                    )
                self._invoke_handler(handler, event)
                return

    @staticmethod
    def _invoke_handler(handler: Callable, event: BaseEvent) -> None:
        """Call a handler with stable UI modules, then restore module state."""
        view_key = 'ubo_app.store.core.view_computation'
        notifications_key = 'ubo_app.store.services.notifications'
        previous_view = sys.modules.get(view_key)
        previous_notifications = sys.modules.get(notifications_key)
        sys.modules[view_key] = _view_computation
        sys.modules[notifications_key] = _notifications_module
        try:
            handler(event)
        finally:
            if previous_view is None:
                sys.modules.pop(view_key, None)
            else:
                sys.modules[view_key] = previous_view
            if previous_notifications is None:
                sys.modules.pop(notifications_key, None)
            else:
                sys.modules[notifications_key] = previous_notifications

    def dispatch(self, action: BaseAction) -> MainState:
        """Dispatch an action, pump follow-up actions, and handle its events."""
        self.dispatched_actions.append(action)
        if not isinstance(action, MainAction):
            return self.state

        result = reducer(self.state, action)
        follow_up_actions: tuple[BaseAction, ...] = ()
        emitted_events: tuple[MainEvent, ...] = ()
        if isinstance(result, CompleteReducerResult):
            self.state = result.state
            follow_up_actions = tuple(result.actions or ())
            emitted_events = tuple(result.events or ())
            self.last_events = list(emitted_events)
            self.all_events.extend(emitted_events)
        elif isinstance(result, MainState):
            self.state = result
            self.last_events = []

        self._sync_current_view()
        for follow_up in follow_up_actions:
            self.dispatch(follow_up)
        for event in emitted_events:
            self.handle_event(event)
        self._sync_current_view()
        return self.state

    def _sync_current_view(self) -> None:
        """Keep ``main.current_view`` aligned with the runner's stack."""
        stack = _view_computation.visible_stack(self.root_state)
        top = stack[-1] if stack else None
        if isinstance(top, NotificationStackItem):
            view = _view_computation.get_notification_view_data(
                self.root_state,
                top.notification_id,
                stack_depth=len(stack),
                page_index=top.page_index,
            )
        else:
            visible_state = replace(self.state, stack=stack)
            view = compute_view_from_dynamic_menus(
                visible_state,
                self.dynamic_menus,
                self.path_mappings,
            )
        self.state = replace(self.state, current_view=view)
