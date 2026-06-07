"""View computation utilities for the dumb UI architecture.

This module provides functions to compute ViewData from the full RootState,
using dynamic menus exclusively. It can be used by both GUI (Kivy) and
non-GUI contexts (gRPC/TUI).
"""

from __future__ import annotations

import math
import socket
from typing import TYPE_CHECKING

from ubo_app.constants import DEBUG_MENU
from ubo_app.logger import logger
from ubo_app.store.core.constants import (
    NOTIFICATION_ACTION_PREFIX,
    NOTIFICATION_DISMISS_PREFIX,
    NOTIFICATION_EXTRA_INFO_PREFIX,
    PAGE_SIZE,
    compute_total_pages,
)
from ubo_app.store.core.types import (
    ApplicationStackItem,
    ApplicationViewData,
    ChatStackItem,
    ChatViewData,
    HomeViewData,
    InstructionStackItem,
    InstructionViewData,
    MenuStackItem,
    MenuViewData,
    NotificationStackItem,
    NotificationViewData,
    ProgressNotificationData,
    PromptStackItem,
    PromptViewData,
    RenderStackItem,
    RenderViewData,
    StatusBarData,
    StatusIconData,
)
from ubo_app.store.core.view_helpers import find_dynamic_menu_for_position
from ubo_app.store.core.view_registry import (
    get_home_view_data,
    get_registered_dependencies,
    get_registered_status_bar_dependencies,
)
from ubo_app.store.services.notifications import NotificationDisplayType

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.store.core.types import StackItemType, ViewData
    from ubo_app.store.main import RootState, UboStore


def _is_background_notification(state: RootState, item: StackItemType) -> bool:
    """Return True iff *item* is a non-screen-owning notification overlay.

    A BACKGROUND notification lives only in the status-bar progress
    wheel; a notification whose backing entry has already been cleared
    from the list is mid-dismissal. Neither should be rendered as the
    current view, even while its ``NotificationStackItem`` is still on
    the navigation stack. Keeping the stack item in place (instead of
    popping it on every progress update) avoids push/pop churn that
    races the view autorun.
    """
    if not isinstance(item, NotificationStackItem):
        return False
    notifications = (
        state.notifications.notifications if hasattr(state, 'notifications') else ()
    )
    notification = next(
        (n for n in notifications if n.id == item.notification_id),
        None,
    )
    return (
        notification is None
        or notification.display_type is NotificationDisplayType.BACKGROUND
    )


def visible_stack(state: RootState) -> tuple[StackItemType, ...]:
    """Return the navigation stack as the on-screen view sees it.

    BACKGROUND (and mid-dismissal) notification overlays are dropped: they
    live only in the status-bar progress wheel, not on screen, even while
    their ``NotificationStackItem`` stays on the stack. Both the view
    computation and the keypad ``choose_by_index`` handler must resolve the
    "top" item through this filter, otherwise a hidden BACKGROUND overlay
    sitting on the raw stack top would steal button presses meant for the
    visible notification underneath it.
    """
    return tuple(
        item
        for item in state.main.stack
        if not _is_background_notification(state, item)
    )


def _hostname_title() -> str:
    """Status-bar title (the device hostname).

    Read at call time — NOT cached in a module-level constant — so the test
    ``socket.gethostname`` mock always applies. Freezing it at import races the
    fixture and leaks the real hostname into snapshots non-deterministically.
    ``gethostname(2)`` is a cheap syscall, so per-status-bar-update is fine.
    """
    return f'󰋜{socket.gethostname()}.local'

__all__ = [
    'PAGE_SIZE',
    'compute_status_bar_data',
    'compute_view_from_root_state',
    'get_chat_view_data',
    'get_notification_view_data',
    'release_view_autorun',
    'setup_dynamic_view_autorun',
    'suppress_view_autorun',
]

# Chat bubble styling — owned by the store (UI logic), not the renderer.
_CHAT_ASSISTANT_BACKGROUND = '#ededed'
_CHAT_ASSISTANT_FOREGROUND = '#1a1d23'
_CHAT_USER_BACKGROUND = '#4f93e0'
_CHAT_USER_FOREGROUND = '#ffffff'

# Gate to suppress redundant view computations during startup (service
# reducer registration burst).  When suppressed, autorun callbacks mark
# dirty instead of computing immediately.  On release, a single
# computation runs if dirty.
# Container pattern (list singletons) avoids ``global`` statements.
_suppressed: list[bool] = [False]
_dirty: list[bool] = [False]
_status_bar_dirty: list[bool] = [False]
_dispatch_fn: list[Callable[[], None] | None] = [None]
_status_bar_dispatch_fn: list[Callable[[], None] | None] = [None]
# Strong references to autorun objects so they aren't garbage collected
# (redux stores the wrapped function as a weak reference).
_autoruns: list[object] = []


def suppress_view_autorun() -> None:
    """Suppress view autorun during startup (e.g. service registration)."""
    _suppressed[0] = True


def release_view_autorun() -> None:
    """Release the startup gate and run one deferred computation if needed."""
    _suppressed[0] = False
    if _dirty[0] and _dispatch_fn[0] is not None:
        _dirty[0] = False
        _dispatch_fn[0]()
    if _status_bar_dirty[0] and _status_bar_dispatch_fn[0] is not None:
        _status_bar_dirty[0] = False
        _status_bar_dispatch_fn[0]()


def get_notification_view_data(
    state: RootState,
    notification_id: str,
    *,
    stack_depth: int = 1,
    page_index: int = 0,
) -> NotificationViewData:
    """Build NotificationViewData with full notification details from state.

    Args:
        state: The full Redux RootState.
        notification_id: The ID of the notification to look up.
        stack_depth: Navigation stack depth for transition animation hints.
        page_index: Current page index for paginated actions.

    Returns:
        NotificationViewData with title, content, icon, color, and items populated.

    """
    from ubo_app.store.core.types import MenuItemData

    notification = None
    if hasattr(state, 'notifications'):
        notification = next(
            (n for n in state.notifications.notifications if n.id == notification_id),
            None,
        )

    if notification:
        # Convert notification actions to MenuItemData
        items: list[MenuItemData | None] = []

        # Add extra_information button if available (shown as info icon on left)
        if notification.extra_information:
            items.append(
                MenuItemData(
                    key='extra_info',
                    label='',
                    icon='\U000f02fc',  # info icon
                    color='#ffffff',
                    is_short=True,
                    action_id=f'{NOTIFICATION_EXTRA_INFO_PREFIX}{notification_id}',
                ),
            )

        # Convert each notification action to MenuItemData
        # Notification items are always is_short=True (compact icon buttons)
        for i, action in enumerate(notification.actions):
            bg_color = (
                action.background_color
                if isinstance(action.background_color, str)
                else None
            )
            items.append(
                MenuItemData(
                    key=action.key or f'action_{i}',
                    label=action.label,
                    icon=action.icon,
                    color=action.color,
                    is_short=True,
                    background_color=bg_color,
                    action_id=f'{NOTIFICATION_ACTION_PREFIX}{notification_id}:{i}',
                ),
            )

        # Add dismiss button at the bottom if show_dismiss_action is True
        show_dismiss = getattr(notification, 'show_dismiss_action', True)
        if show_dismiss:
            items.append(
                MenuItemData(
                    key='dismiss',
                    label='',
                    icon='\uf00d',  # close/X icon
                    color='#ffffff',
                    is_short=True,
                    background_color='#C0C0C0',
                    action_id=f'{NOTIFICATION_DISMISS_PREFIX}{notification_id}',
                ),
            )

        # Compute pagination metadata — the full item list is sent to the
        # GUI which handles per-page slicing and half-item peek rendering,
        # just like MenuViewData.
        total_pages = compute_total_pages(len(items))
        page_index = min(page_index, max(total_pages - 1, 0))

        # Extract extra information text if available
        extra_info_text = ''
        if notification.extra_information:
            extra_info_text = notification.extra_information.text

        return NotificationViewData(
            notification_id=notification_id,
            title=notification.title,
            content=notification.content,
            icon=notification.icon,
            color=notification.color,
            items=tuple(items),
            extra_information=extra_info_text,
            page_index=page_index,
            total_pages=total_pages,
            show_status_bar=False,
            stack_depth=stack_depth,
        )

    # Fallback if notification not found (edge case)
    return NotificationViewData(
        notification_id=notification_id,
        show_status_bar=False,
        stack_depth=stack_depth,
    )


def get_chat_view_data(
    state: RootState,
    stack_item: ChatStackItem,
    *,
    stack_depth: int = 1,
) -> ChatViewData:
    """Build ChatViewData from the chat slice and the stack scroll position.

    The store owns the *conversation* — message history, who said what,
    bubble styling, audio data and the integer scroll offset. The L1/L2/L3
    pointer binding is deliberately *not* computed here: which bubble lines
    up with which hardware-button row depends on rendered bubble heights, a
    pure layout concern the GUI renderer owns (see ``ChatWidget``).

    Args:
        state: The full Redux RootState.
        stack_item: The chat stack item (holds the scroll offset).
        stack_depth: Navigation stack depth for transition animation hints.

    Returns:
        ChatViewData with fully-styled bubbles and the scroll position.

    """
    from ubo_app.store.core.types import ChatBubbleData
    from ubo_app.store.services.chat import ChatRole

    messages = list(state.chat.messages) if hasattr(state, 'chat') else []
    total = len(messages)

    # Clamp the scroll offset to the available history.
    scroll_offset = min(max(stack_item.scroll_offset, 0), max(0, total - 1))

    bubbles: list[ChatBubbleData] = []
    for message in messages:
        is_user = message.role == ChatRole.USER
        bubbles.append(
            ChatBubbleData(
                message_id=message.id,
                role=message.role.value,
                alignment='right' if is_user else 'left',
                kind=message.kind.value,
                text=message.text,
                color=(
                    _CHAT_USER_FOREGROUND
                    if is_user
                    else _CHAT_ASSISTANT_FOREGROUND
                ),
                background_color=(
                    _CHAT_USER_BACKGROUND
                    if is_user
                    else _CHAT_ASSISTANT_BACKGROUND
                ),
                is_playing=message.is_playing,
                waveform=tuple(message.waveform),
            ),
        )

    return ChatViewData(
        bubbles=tuple(bubbles),
        scroll_offset=scroll_offset,
        total_bubbles=total,
        stack_depth=stack_depth,
    )


def compute_status_bar_data(state: RootState) -> StatusBarData:
    """Compute StatusBarData from the full Redux state.

    This consolidates all status bar information from various state slices
    into a single serializable object.
    """
    # Compute progress notifications from notifications with progress
    progress_notifications: list[ProgressNotificationData] = []
    if hasattr(state, 'notifications') and state.notifications.notifications:
        progress_notifications = [
            ProgressNotificationData(
                id=notification.id,
                progress=(
                    None if math.isnan(notification.progress) else notification.progress
                ),
                color=notification.color,
            )
            for notification in state.notifications.notifications
            if notification.progress is not None
        ]

    # Compute icons from status_icons state
    icons: tuple[StatusIconData, ...] = ()
    if hasattr(state, 'status_icons') and state.status_icons.icons is not None:
        try:
            icons = tuple(
                StatusIconData(symbol=icon.symbol, color=icon.color)
                for icon in state.status_icons.icons
            )
        except (AttributeError, TypeError) as e:
            if DEBUG_MENU:
                logger.warning('[ViewRenderer] Failed to compute icons: %s', e)

    # Get temperature and light from sensors
    temperature: float | None = None
    light_level: float | None = None
    if hasattr(state, 'sensors'):
        temperature = getattr(
            getattr(state.sensors, 'temperature', None),
            'value',
            None,
        )
        light_level = getattr(
            getattr(state.sensors, 'light', None),
            'value',
            None,
        )

    # Get system metrics (clock)
    clock = getattr(getattr(state, 'system', None), 'clock', '') or ''

    # Get recording states
    main = getattr(state, 'main', None)
    is_recording = getattr(main, 'is_recording', False)
    is_replaying = getattr(main, 'is_replaying', False)
    is_recording_audio = getattr(
        getattr(state, 'audio', None),
        'is_recording',
        False,
    )

    return StatusBarData(
        title=_hostname_title(),
        is_recording=is_recording,
        is_replaying=is_replaying,
        is_recording_audio=is_recording_audio,
        progress_notifications=tuple(progress_notifications),
        clock=clock,
        temperature=temperature,
        light_level=light_level,
        icons=icons,
    )


def _notification_view_dependency(notification: object) -> tuple[object, ...]:
    """Return notification fields that affect NotificationViewData."""
    extra_information = getattr(notification, 'extra_information', None)
    actions = getattr(notification, 'actions', ()) or ()
    return (
        getattr(notification, 'id', None),
        getattr(notification, 'title', ''),
        getattr(notification, 'content', ''),
        getattr(notification, 'icon', ''),
        getattr(notification, 'color', ''),
        getattr(notification, 'progress', None),
        # display_type drives whether the overlay is rendered on screen
        # at all (STICKY/FLASH) or filtered out (BACKGROUND), so the view
        # autorun must recompute when it changes.
        getattr(notification, 'display_type', None),
        getattr(notification, 'show_dismiss_action', True),
        getattr(extra_information, 'text', None),
        tuple(
            (
                getattr(action, 'key', None),
                getattr(action, 'label', ''),
                getattr(action, 'icon', ''),
                getattr(action, 'color', ''),
                getattr(action, 'background_color', None),
                getattr(action, 'action_id', None),
                getattr(action, 'close_notification', False),
                getattr(action, 'dismiss_notification', False),
            )
            for action in actions
        ),
    )


def _chat_view_dependency(state: RootState) -> tuple[object, ...]:
    """Return chat-slice fields that affect ChatViewData.

    Added to the view autorun selector so adding a message (which changes
    ``state.chat`` but not ``state.main.stack``) still triggers a view
    recomputation. Returns a single revision counter rather than hashing
    every message field per LLM token — the reducer bumps the counter on
    every mutation, so selector equality work stays ``O(1)`` regardless
    of history length. ``is_playing`` flips outside the streaming hot
    path but still needs to invalidate the view, so it's folded into the
    dependency tuple alongside the revision.
    """
    chat = getattr(state, 'chat', None)
    if chat is None:
        return (0, ())
    return (
        chat.messages_revision,
        tuple(message.is_playing for message in chat.messages),
    )


def compute_view_from_root_state(state: RootState) -> ViewData:  # noqa: C901, PLR0912
    """Compute ViewData from the full RootState, using dynamic menus.

    This is the dumb UI architecture's view computation function. It uses
    dynamic menus exclusively for all menu views.

    Args:
        state: The full Redux RootState.

    Returns:
        ViewData describing what the UI should render.

    """
    from ubo_app.store.core.menus import HOME_MENU_ID

    main_state = state.main
    dynamic_menus_state = state.dynamic_menus
    stack = main_state.stack

    if not stack:
        return HomeViewData()

    # Drop BACKGROUND (and mid-dismissal) notification overlays — they
    # belong in the status-bar progress wheel, not on screen. The stack
    # item stays put; this filter is what makes the
    # STICKY → BACKGROUND → FLASH lifecycle work without popping and
    # re-pushing the notification (which raced the view autorun).
    stack = visible_stack(state)

    if not stack:
        return HomeViewData()

    top_item = stack[-1]

    # Handle application views
    if isinstance(top_item, ApplicationStackItem):
        return ApplicationViewData(
            application_id=top_item.application_id,
            show_status_bar=False,
            extra_data=dict(top_item.initialization_kwargs),
            stack_depth=len(stack),
        )

    if isinstance(top_item, RenderStackItem):
        return RenderViewData(
            kind=top_item.kind,
            title=top_item.title,
            show_status_bar=False,
            props=dict(top_item.props),
            items=top_item.items,
            stream_id=top_item.stream_id,
            stack_depth=len(stack),
        )

    # Handle chat overlay views
    if isinstance(top_item, ChatStackItem):
        return get_chat_view_data(
            state,
            top_item,
            stack_depth=len(stack),
        )

    # Handle notification views
    if isinstance(top_item, NotificationStackItem):
        return get_notification_view_data(
            state,
            top_item.notification_id,
            stack_depth=len(stack),
            page_index=top_item.page_index,
        )

    # Handle instruction views
    if isinstance(top_item, InstructionStackItem):
        return InstructionViewData(
            title=top_item.title,
            instruction=top_item.instruction,
            icon=top_item.icon,
            spinner=top_item.spinner,
            timeout_seconds=top_item.timeout_seconds,
            progress_text=top_item.progress_text,
            footer_text=top_item.footer_text,
            stack_depth=len(stack),
        )

    # Handle prompt views
    if isinstance(top_item, PromptStackItem):
        return PromptViewData(
            title=top_item.title,
            prompt=top_item.prompt,
            icon=top_item.icon,
            items=top_item.items,
            stack_depth=len(stack),
        )

    # Must be MenuStackItem
    if not isinstance(top_item, MenuStackItem):
        return HomeViewData()

    # Check if we're at home (depth 1)
    depth = len([i for i in stack if isinstance(i, MenuStackItem)])
    if depth <= 1:
        # Home view - get items from the HOME_MENU_ID dynamic menu
        home_data = get_home_view_data(state)
        cpu_percent = home_data.get('cpu_percent', 50.0)
        ram_percent = home_data.get('ram_percent', 50.0)
        volume_level = home_data.get('volume_level', 0.0)

        from ubo_app.store.core.types import MenuItemData

        home_items: tuple[MenuItemData, ...] = ()
        home_menu = dynamic_menus_state.menus.get(HOME_MENU_ID)
        if home_menu is not None:
            home_items = tuple(item for item in home_menu.items if item is not None)

        return HomeViewData(
            show_status_bar=True,
            menu_items=home_items,
            cpu_percent=cpu_percent,
            ram_percent=ram_percent,
            volume_level=volume_level,
        )

    # First, try direct lookup: the top stack item's menu_key may itself
    # be a registered dynamic menu ID (e.g. filesystem directories use
    # 'file-system:dir:/path' as both the menu_key and the dynamic menu ID).
    direct_menu = dynamic_menus_state.menus.get(top_item.menu_key)
    if direct_menu is None:
        # Fall back to path-based matching for services where menu_key
        # differs from the dynamic menu ID.
        dynamic_match = find_dynamic_menu_for_position(
            main_state,
            dynamic_menus_state,
            stack,
        )
        if dynamic_match is not None:
            menu_id, _ = dynamic_match
            direct_menu = dynamic_menus_state.menus.get(menu_id)

    if direct_menu is not None:
        items = direct_menu.items
        total_pages = compute_total_pages(
            len(items),
            is_headed=direct_menu.heading is not None,
        )
        # Clamp page_index to valid range in case dynamic menu
        # items changed and the old page_index is now out of bounds.
        page_index = min(top_item.page_index, max(total_pages - 1, 0))

        return MenuViewData(
            show_status_bar=page_index == 0,
            title=direct_menu.title,
            heading=direct_menu.heading,
            sub_heading=direct_menu.sub_heading,
            items=items,
            placeholder=direct_menu.placeholder,
            page_index=page_index,
            total_pages=total_pages,
            stack_depth=len(stack),
        )

    # No dynamic menu found - return empty menu view
    return MenuViewData(
        show_status_bar=True,
        title='',
        items=(),
        page_index=0,
        total_pages=1,
        stack_depth=len(stack),
    )


def _dispatch_view_update(state: RootState, store: UboStore) -> None:
    """Compute view and status bar, then dispatch if changed.

    ``store`` is threaded in by the caller (see ``setup_dynamic_view_autorun``) rather
    than imported here: this runs on the scheduler thread, and a deferred
    ``from ubo_app.store.main import store`` can be re-isolated by the service-thread
    import machinery into a fresh module load that trips the store's main-thread guard.
    """
    if not hasattr(state, 'main'):
        return
    from ubo_app.store.core.types import (
        MenuStackItem,
        MenuViewData,
        NotificationStackItem,
        NotificationViewData,
        StackSetPageIndexAction,
        UpdateCurrentViewAction,
    )

    computed_view = compute_view_from_root_state(state)
    computed_status_bar = compute_status_bar_data(state)

    view_changed = state.main.current_view != computed_view
    status_bar_changed = state.main.status_bar != computed_status_bar

    # If the view clamped page_index, sync it back to the stack item to
    # prevent stale page indices from resurfacing when items change later.
    if state.main.stack:
        top = state.main.stack[-1]
        if (
            isinstance(computed_view, (MenuViewData, NotificationViewData))
            and isinstance(top, (MenuStackItem, NotificationStackItem))
            and computed_view.page_index != top.page_index
        ):
            store.dispatch(
                StackSetPageIndexAction(page_index=computed_view.page_index),
            )

    if view_changed or status_bar_changed:
        logger.debug(
            'view_computation: dispatching update '
            '(view_changed=%s, status_bar_changed=%s)',
            view_changed,
            status_bar_changed,
        )
        store.dispatch(
            UpdateCurrentViewAction(
                view=computed_view,
                status_bar=computed_status_bar,
            ),
        )


def _dispatch_status_bar_update(state: RootState, store: UboStore) -> None:
    """Compute status bar and view freshly, dispatch if either changed.

    The view is recomputed from scratch via ``compute_view_from_root_state``
    rather than snapshotting ``state.main.current_view``. Snapshotting the
    *output* (``current_view``) is unsafe: this autorun runs as a synchronous
    listener while the action queue is still draining, so the snapshot lags
    behind any pending view change. Re-dispatching that stale snapshot makes
    the reducer clobber the newer view back to the old one — the notification
    ⇄ menu flicker seen during Piper voice downloads (the status-bar autorun
    fires dozens of times a second on progress updates). Recomputing from the
    *inputs* (stack, notifications, dynamic menus) is always correct, and the
    ``UpdateCurrentViewAction`` reducer dedupes redundant dispatches.
    """
    if not hasattr(state, 'main'):
        return
    from ubo_app.store.core.types import UpdateCurrentViewAction

    computed_status_bar = compute_status_bar_data(state)
    computed_view = compute_view_from_root_state(state)
    status_bar_changed = state.main.status_bar != computed_status_bar
    view_changed = state.main.current_view != computed_view

    if view_changed or status_bar_changed:
        logger.debug(
            'view_computation: status-bar autorun dispatching '
            '(view_changed=%s, status_bar_changed=%s)',
            view_changed,
            status_bar_changed,
        )
        store.dispatch(
            UpdateCurrentViewAction(
                view=computed_view,
                status_bar=computed_status_bar,
            ),
        )


def setup_dynamic_view_autorun() -> None:
    """Set up autoruns to update current_view and status_bar when state changes.

    This should be called after the store is initialized.  Two autoruns are
    created to separate concerns:

    1. **View autorun** - watches navigation stack, dynamic menus,
       notifications, and registered apps.  Fires infrequently (on user
       interaction / service registration).

    2. **Status-bar autorun** - watches home-view data (CPU, RAM, volume)
       and status-bar dependencies (clock, temperature, icons).  Fires more
       often but only recomputes status bar data (cheap).
    """
    from redux import AutorunOptions

    from ubo_app.store.main import store

    @store.with_state(lambda state: state)
    def _view_dispatch(state: RootState) -> None:
        _dispatch_view_update(state, store)

    @store.with_state(lambda state: state)
    def _status_bar_dispatch(state: RootState) -> None:
        _dispatch_status_bar_update(state, store)

    # Store references so release_view_autorun() can trigger deferred computations
    _dispatch_fn[0] = _view_dispatch  # type: ignore[assignment]
    _status_bar_dispatch_fn[0] = _status_bar_dispatch  # type: ignore[assignment]

    # -- View autorun (infrequent) ------------------------------------------

    @store.autorun(
        lambda state: (
            state.main.stack,
            state.dynamic_menus.version,
            state.main.is_recording,
            state.main.is_replaying,
            tuple(state.main.registered_apps.keys()),
            tuple(
                _notification_view_dependency(n)
                for n in (
                    state.notifications.notifications
                    if hasattr(state, 'notifications')
                    else ()
                )
            ),
            _chat_view_dependency(state),
            get_registered_dependencies(state),
        ),
        options=AutorunOptions(default_value=None),
    )
    def _update_view_on_navigation_change(_: tuple | None) -> None:
        """Update current_view when stack, dynamic menus, etc. change."""
        if _suppressed[0]:
            _dirty[0] = True
            return
        _view_dispatch()  # type: ignore[call-arg]

    # -- Status-bar autorun (frequent but cheap) ----------------------------

    @store.autorun(
        lambda state: (
            get_home_view_data(state),
            get_registered_status_bar_dependencies(state),
        ),
        options=AutorunOptions(default_value=None),
    )
    def _update_status_bar_on_metrics_change(_: tuple | None) -> None:
        """Update status bar when metrics / clock / icons change."""
        if _suppressed[0]:
            _status_bar_dirty[0] = True
            return
        _status_bar_dispatch()  # type: ignore[call-arg]

    # Keep strong references so the autoruns (and their wrapped functions)
    # survive after this function returns.
    _autoruns.extend(
        [
            _update_view_on_navigation_change,
            _update_status_bar_on_metrics_change,
        ],
    )
