# UI Redux Architecture: GUI Stack Migration

This document explains the architecture of UI logic handling within the Redux store and reducer logic, introduced in the `gui-stack-migration` branch.

## Overview

The migration decouples UI state management from `ubo-gui` (the Kivy-based frontend) and centralizes it in Redux. This enables **thin client applications** that are pure renderers of state, with all navigation, menu, and view logic handled by the backend (ubo_app).

### Before: ubo-gui Managed State

```
┌─────────────────────────────────────────────────────────┐
│                       ubo-gui                           │
│  ┌─────────────────────────────────────────────────┐   │
│  │  Menu Stack State  │  Widget Lifecycle  │  Nav  │   │
│  └─────────────────────────────────────────────────┘   │
│                          ↑                              │
│                    Tight Coupling                       │
└─────────────────────────────────────────────────────────┘
                           ↑
              Services return UI objects
```

### After: Redux Manages All UI State

```
┌─────────────────────────────────────────────────────────┐
│                     ubo_app (Redux)                     │
│  ┌─────────────────────────────────────────────────┐   │
│  │  Stack  │  ViewData  │  StatusBar  │  Menus     │   │
│  └─────────────────────────────────────────────────┘   │
│                          ↓                              │
│              ViewChangedEvent (serializable)            │
└─────────────────────────────────────────────────────────┘
            ↓                    ↓                    ↓
      ┌─────────┐          ┌─────────┐          ┌─────────┐
      │  Kivy   │          │  Web UI │          │ Remote  │
      │  (GUI)  │          │ (React) │          │  TUI    │
      └─────────┘          └─────────┘          └─────────┘
           Pure Renderers - No UI Logic
```

## Core Concepts

### 1. Navigation Stack

The navigation state is a tuple of immutable stack items:

```python
# ubo_app/store/core/types.py

class MenuStackItem(Immutable):
    id: str           # Unique instance identifier (UUID)
    menu_key: str     # Menu lookup key (e.g., 'settings', 'wifi:connections')
    page_index: int   # Current pagination position

class ApplicationStackItem(Immutable):
    id: str
    application_id: str              # e.g., 'camera:viewfinder'
    initialization_args: tuple       # Constructor args
    initialization_kwargs: dict      # Constructor kwargs

class NotificationStackItem(Immutable):
    id: str
    notification_id: str             # Which notification to display

StackItemType = MenuStackItem | ApplicationStackItem | NotificationStackItem
```

The stack is the **single source of truth** for navigation:
- Empty stack → Home screen
- `MenuStackItem` on top → Menu view
- `ApplicationStackItem` on top → Full-screen application
- `NotificationStackItem` on top → Notification overlay

### 2. ViewData Types

Serializable, immutable types that define **what to render**:

```python
# ubo_app/store/core/types.py

class MenuItemData(Immutable):
    key: str                        # Unique identifier
    label: str                      # Display text
    icon: str                       # Nerd Font symbol
    color: str = '#ffffff'          # Icon color
    is_short: bool = False          # Layout hint
    action_id: str | None = None    # Handler lookup key
    background_color: str | None = None

class HomeViewData(Immutable):
    menu_items: tuple[MenuItemData, ...] = ()
    cpu_percent: float = 0.0
    ram_percent: float = 0.0
    volume_level: float = 0.0

class MenuViewData(Immutable):
    title: str = ''
    items: tuple[MenuItemData | None, ...] = ()
    page_index: int = 0
    total_pages: int = 1
    placeholder: str = ''

class ApplicationViewData(Immutable):
    application_id: str
    extra_data: dict = field(default_factory=dict)

class NotificationViewData(Immutable):
    notification_id: str
    title: str = ''
    content: str = ''
    icon: str = ''
    color: str = '#ffffff'

ViewData = HomeViewData | MenuViewData | ApplicationViewData | NotificationViewData
```

### 3. StatusBarData

Consolidates header/footer state from multiple slices:

```python
class StatusBarData(Immutable):
    # Header
    title: str = ''
    is_recording: bool = False
    is_replaying: bool = False
    is_recording_audio: bool = False
    progress_notifications: tuple[ProgressNotificationData, ...] = ()

    # Footer
    clock: str = ''                  # "14:30"
    temperature: float | None = None
    light_level: float | None = None
    icons: tuple[StatusIconData, ...] = ()
```

## Stack Actions

Redux actions for navigation manipulation:

| Action | Effect |
|--------|--------|
| `StackPushMenuAction(menu_key)` | Navigate into submenu |
| `StackPushApplicationAction(application_id, ...)` | Open full-screen application |
| `StackPushNotificationAction(notification_id)` | Show notification overlay |
| `StackPopAction(count=1)` | Pop N items from stack |
| `StackPopToRootAction()` | Return to home screen |
| `StackPopItemAction(item_id)` | Remove specific item by ID |
| `StackSetPageIndexAction(page_index)` | Change pagination |

Example:
```python
# Navigate to Wi-Fi settings
store.dispatch(StackPushMenuAction(menu_key='wifi:connections'))

# Go back
store.dispatch(StackPopAction())

# Return to home
store.dispatch(StackPopToRootAction())
```

## Reducer Logic

### Stack Push Flow

```python
# ubo_app/store/core/reducer.py

case StackPushMenuAction():
    new_item = MenuStackItem(
        id=uuid.uuid4().hex,
        menu_key=action.menu_key,
        page_index=0
    )
    new_stack = (*state.stack, new_item)
    new_state = replace(state, stack=new_stack, depth=len(new_stack))
    new_view = compute_view_from_stack(new_state)

    return CompleteReducerResult(
        state=replace(new_state, current_view=new_view),
        events=[StackChangedEvent(stack=new_stack), ViewChangedEvent(view=new_view)]
    )
```

### View Computation

The `compute_view_from_stack()` function converts the navigation stack to ViewData:

```python
def compute_view_from_stack(state: MainState) -> ViewData:
    if not state.stack:
        return HomeViewData()  # Empty stack → home

    top_item = state.stack[-1]

    if isinstance(top_item, ApplicationStackItem):
        return ApplicationViewData(application_id=top_item.application_id, ...)

    if isinstance(top_item, NotificationStackItem):
        return NotificationViewData(notification_id=top_item.notification_id, ...)

    # MenuStackItem → build menu view
    if state.depth <= 1:
        return HomeViewData(menu_items=..., cpu_percent=..., ...)

    return MenuViewData(title=..., items=..., page_index=..., total_pages=...)
```

## Dynamic Menus

Services provide runtime menu content without coupling to UI:

```python
# Service dispatches menu content
class DynamicMenuData(Immutable):
    menu_id: str                              # e.g., 'wifi:connections'
    title: str = ''
    items: tuple[MenuItemData | None, ...] = ()
    placeholder: str = ''

# Action to update
store.dispatch(UpdateDynamicMenuAction(
    menu_id='wifi:connections',
    title='Wi-Fi Networks',
    items=tuple(
        MenuItemData(
            key=conn.ssid,
            label=conn.ssid,
            icon='󱚵',
            action_id=f'wifi:connect:{conn.ssid}'
        )
        for conn in connections
    )
))
```

Dynamic menus are stored in `DynamicMenusState.menus` and referenced by `menu_key` in stack items.

## Action Registry

Menu item clicks are decoupled via an action registry:

```python
# ubo_app/store/core/action_registry.py

def register_action(action_id: str, handler: Callable[[], None]) -> None:
    _action_handlers[action_id] = handler

def execute_action(action_id: str) -> bool:
    handler = _action_handlers.get(action_id)
    if handler:
        handler()
        return True
    return False

# Services register handlers
register_action('wifi:scan', lambda: store.dispatch(WiFiScanAction()))
register_action('power:reboot', lambda: store.dispatch(RebootAction()))
```

When a UI client dispatches `ExecuteMenuActionAction(action_id='wifi:scan')`, the reducer calls `execute_action()` which invokes the registered handler.

## Event Flow

Complete action → view update flow:

```
User Input (tap menu item)
         ↓
┌────────────────────────────────────────────────────────────────┐
│ UI Client dispatches: ExecuteMenuActionAction(action_id='...')│
└────────────────────────────────────────────────────────────────┘
         ↓
┌────────────────────────────────────────────────────────────────┐
│ Reducer: execute_action() → handler() → dispatch new actions  │
└────────────────────────────────────────────────────────────────┘
         ↓
┌────────────────────────────────────────────────────────────────┐
│ Stack actions update state.stack                               │
│ compute_view_from_stack() produces new ViewData               │
└────────────────────────────────────────────────────────────────┘
         ↓
┌────────────────────────────────────────────────────────────────┐
│ Redux emits: ViewChangedEvent(view=HomeViewData(...))         │
│              StackChangedEvent(stack=(...))                    │
└────────────────────────────────────────────────────────────────┘
         ↓
┌────────────────────────────────────────────────────────────────┐
│ All UI clients receive events and re-render                   │
└────────────────────────────────────────────────────────────────┘
```

## MainState Structure

```python
class MainState(Immutable):
    menu: Menu | None = None              # Legacy ubo-gui menu tree

    # PRIMARY: New navigation stack (source of truth)
    stack: tuple[StackItemType, ...] = ()

    # DERIVED: For backward compatibility
    path: Sequence[str] = field(default_factory=list)
    depth: int = 0

    # Header/footer visibility
    is_header_visible: bool = True
    is_footer_visible: bool = True

    # Recording/replay
    is_recording: bool = False
    is_replaying: bool = False

    # COMPUTED: Updated by view computation
    current_view: ViewData | None = None
    status_bar: StatusBarData | None = None
```

## Thin Client Protocol

Thin clients only need to:

1. **Subscribe** to `ViewChangedEvent` and `StatusBarChangedEvent`
2. **Render** the received ViewData/StatusBarData
3. **Dispatch** user actions (e.g., `ExecuteMenuActionAction`, `StackPopAction`)

### Example: Remote TUI Client

```python
# Pseudocode for a thin client

async def main():
    # Connect to ubo_app via gRPC
    channel = grpc.aio.insecure_channel('device:50051')
    stub = UboAppStub(channel)

    # Subscribe to view changes
    async for event in stub.SubscribeViewChanges(Empty()):
        render_view(event.view_data)

def render_view(view: ViewData):
    match view:
        case HomeViewData():
            render_home(view.cpu_percent, view.ram_percent, view.menu_items)
        case MenuViewData():
            render_menu(view.title, view.items, view.page_index)
        case ApplicationViewData():
            render_app(view.application_id, view.extra_data)
        case NotificationViewData():
            render_notification(view.title, view.content, view.icon)

def on_item_click(item: MenuItemData):
    stub.DispatchAction(ExecuteMenuActionAction(action_id=item.action_id))
```

## Migration Patterns

### Old Pattern: Services Return UI Objects

```python
# WRONG: Tight coupling to ubo-gui
@store.autorun(lambda state: state.wifi.connections)
def wireless_connections_menu(connections):
    return HeadlessMenu(
        title='Wi-Fi',
        items=[ActionItem(label=c.ssid, action=connect_wifi) for c in connections]
    )
```

### New Pattern: Services Dispatch State Updates

```python
# CORRECT: Decoupled via Redux
@store.autorun(lambda state: state.wifi.connections)
def wireless_connections_menu(connections):
    items = tuple(
        MenuItemData(
            key=conn.ssid,
            label=conn.ssid,
            icon='󱚵',
            action_id=f'wifi:connect:{conn.ssid}'
        )
        for conn in (connections or [])
    )
    store.dispatch(UpdateDynamicMenuAction(
        menu_id='wifi:connections',
        title='Wi-Fi',
        items=items
    ))
```

## Benefits

| Benefit | Description |
|---------|-------------|
| **Platform Independence** | Build UIs on any platform (iOS, Android, Web, Terminal) |
| **State Serialization** | Full UI state can be serialized for debugging/replay |
| **Single Source of Truth** | No UI state divergence between clients |
| **Testability** | UI logic tested via Redux reducers, not widget tests |
| **Remote Clients** | Enable WearOS, Apple Watch, Web dashboard clients |
| **Time Travel Debugging** | Redux DevTools can inspect/replay UI state |
| **Thin Clients** | Clients are pure renderers with minimal logic |

## Key Files

| File | Purpose |
|------|---------|
| `ubo_app/store/core/types.py` | Stack items, ViewData types, actions |
| `ubo_app/store/core/reducer.py` | Main reducer with stack operations |
| `ubo_app/store/core/view_computation.py` | ViewData computation from state |
| `ubo_app/store/core/action_registry.py` | Menu action handler registry |
| `ubo_app/store/core/dynamic_menus_reducer.py` | Dynamic menu state management |
| `ubo_app/store/main.py` | RootState combining all slices |

## Backward Compatibility

The architecture maintains backward compatibility with existing code:

- `MainState.menu` still holds the legacy ubo-gui Menu tree
- `derive_path_from_stack()` computes legacy `path` from new stack
- Services can still register menus via old APIs
- `find_menu_for_item()` traverses legacy tree when needed

New code should use the stack-based navigation and dynamic menus exclusively.
